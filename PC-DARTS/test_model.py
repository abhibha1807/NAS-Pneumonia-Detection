import os
import sys
import time
import glob
import numpy as np
import torch
import utils
import logging
import argparse
import torch.nn as nn
import genotypes
import torch.utils
import torchvision.datasets as dset
import torch.backends.cudnn as cudnn
import torch.nn.functional as F
from torch.autograd import Variable
from model import NetworkCIFAR as Network
from torchvision import transforms, datasets, models
from PIL import ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

#0.025, 0.001
parser = argparse.ArgumentParser("cifar")
parser.add_argument('--data', type=str, default='/abhibha-volume/Image-Enhancer/', help='location of the data corpus')
parser.add_argument('--set', type=str, default='cifar10', help='location of the data corpus')
parser.add_argument('--batch_size', type=int, default=16, help='batch size')
parser.add_argument('--learning_rate', type=float, default=0.025, help='init learning rate')
parser.add_argument('--momentum', type=float, default=0.9, help='momentum')
parser.add_argument('--weight_decay', type=float, default=3e-4, help='weight decay')
parser.add_argument('--report_freq', type=float, default=50, help='report frequency')
parser.add_argument('--gpu', type=int, default=0, help='gpu device id')
parser.add_argument('--epochs', type=int, default=20, help='num of training epochs')
parser.add_argument('--init_channels', type=int, default=36, help='num of init channels')
parser.add_argument('--layers', type=int, default=20, help='total number of layers')
parser.add_argument('--model_path', type=str, default='saved_models', help='path to save the model')
parser.add_argument('--auxiliary', action='store_true', default=True, help='use auxiliary tower')
parser.add_argument('--auxiliary_weight', type=float, default=0.4, help='weight for auxiliary loss')
parser.add_argument('--cutout', action='store_true', default=True, help='use cutout')
parser.add_argument('--cutout_length', type=int, default=16, help='cutout length')
parser.add_argument('--drop_path_prob', type=float, default=0.3, help='drop path probability')
parser.add_argument('--save', type=str, default='EXP', help='experiment name')
parser.add_argument('--seed', type=int, default=0, help='random seed')
parser.add_argument('--arch', type=str, default='PCDARTS', help='which architecture to use')
parser.add_argument('--grad_clip', type=float, default=5, help='gradient clipping')
args = parser.parse_args()

args.save = 'cleaned-test-copy-eval-{}-{}'.format(args.save, time.strftime("%Y%m%d-%H%M%S"))
utils.create_exp_dir(args.save, scripts_to_save=glob.glob('*.py'))

log_format = '%(asctime)s %(message)s'
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
    format=log_format, datefmt='%m/%d %I:%M:%S %p')
fh = logging.FileHandler(os.path.join(args.save, 'log.txt'))
fh.setFormatter(logging.Formatter(log_format))
logging.getLogger().addHandler(fh)

CIFAR_CLASSES = 2
# sig = nn.Softmax(dim=1)
# sig = nn.LogSoftmax(dim=1)
sig = nn.Sigmoid()
def main():
  if not torch.cuda.is_available():
    logging.info('no gpu device available')
    sys.exit(1)
  torch.backends.cudnn.enabled = False
  np.random.seed(args.seed)
  torch.cuda.set_device(args.gpu)
  cudnn.benchmark = True
  torch.manual_seed(args.seed)
  cudnn.enabled=True
  torch.cuda.manual_seed(args.seed)
  logging.info('gpu device = %d' % args.gpu)
  logging.info("args = %s", args)

  genotype = eval("genotypes.%s" % args.arch)
  logging.info('genotype = %s', genotype)
  model = Network(args.init_channels, CIFAR_CLASSES, args.layers, args.auxiliary, genotype)
  #utils.load(model, '/abhibha-volume/PCDARTS-cifar10/cleaned-test-copy-eval-EXP-20210919-081525/weights.pt')
  model = model.cuda()

  #model.load_state_dict(torch.load(model_path))


  pretrained_dict = torch.load('/abhibha-volume/PCDARTS-cifar10/cleaned-test-copy-eval-EXP-20210919-081525/weights.pt')
  model_dict = model.state_dict()

  # 1. filter out unnecessary keys
  print(len(pretrained_dict.keys()))
  pretrained_dict = {k: v for k, v in pretrained_dict.items() if k in model_dict}
  print(len(pretrained_dict.keys()))
  # 2. overwrite entries in the existing state dict
  model_dict.update(pretrained_dict) 
  # 3. load the new state dict
  model.load_state_dict(pretrained_dict, strict=False )

  logging.info("param size = %fMB", utils.count_parameters_in_MB(model))

  criterion = nn.CrossEntropyLoss()
  
  # criterion = nn.BCELoss()
  # criterion = nn.MSELoss()
  criterion = criterion.cuda()
  optimizer = torch.optim.SGD(
      model.parameters(),
      args.learning_rate,
      momentum=args.momentum,
      weight_decay=args.weight_decay
      )

  train_transform, valid_transform = utils._data_transforms_cifar10(args)

  # train_data = dset.CIFAR10(root=args.data, train=True, download=True, transform=train_transform)
  # valid_data = dset.CIFAR10(root=args.data, train=False, download=True, transform=valid_transform)

  datadir=args.data
  print(datadir)
  traindir = datadir + '/cleaned_train/'
  validdir = datadir + '/cleaned_val_copy/'
  testdir = datadir + '/cleaned_test_copy/'
  data = {
  'train':
  datasets.ImageFolder(root=traindir, transform=train_transform),
  'val':
  datasets.ImageFolder(root=validdir, transform=valid_transform),
  'test':
  datasets.ImageFolder(root=testdir, transform=valid_transform)
}

  train_data=data['train']
  valid_data=data['test']

  for i in train_data:
      print(i[0].shape)
      break
  print('\n')
  for i in valid_data:
    print(i[0].shape)
    break
 
  train_queue = torch.utils.data.DataLoader(
      train_data, batch_size=args.batch_size, shuffle=True, pin_memory=True, num_workers=2)

  valid_queue = torch.utils.data.DataLoader(
      valid_data, batch_size=args.batch_size, shuffle=False, pin_memory=True, num_workers=2)

  scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, float(args.epochs))
  
  best_acc = 0.0
  for epoch in range(args.epochs):
    scheduler.step()
    logging.info('epoch %d lr %e', epoch, scheduler.get_lr()[0])
    model.drop_path_prob = args.drop_path_prob * epoch / args.epochs

    # train_acc, train_obj = train(train_queue, model, criterion, optimizer)
    # logging.info('train_acc %f', train_acc)

    valid_acc, valid_obj = infer(valid_queue, model, criterion)
    if valid_acc > best_acc:
        best_acc = valid_acc
    logging.info('valid_acc %f, best_acc %f', valid_acc, best_acc)

    utils.save(model, os.path.join(args.save, 'weights.pt'))


def train(train_queue, model, criterion, optimizer):
  objs = utils.AvgrageMeter()
  top1 = utils.AvgrageMeter()
  top5 = utils.AvgrageMeter()
  model.train()

  for step, (input, target) in enumerate(train_queue):
    # if torch.cuda.is_available():
      input = Variable(input).cuda()
      target = Variable(target).cuda()
      # print(input.shape, target.shape)
      optimizer.zero_grad()
      logits, logits_aux = model(input)
      # print('logits:', logits, logits.shape)
      # print('taregt:',target, target.shape)

      #nlogits=torch.max(logits)
      nlogits, indices = torch.max(logits, 1)
      # nlogits=torch.unsqueeze(nlogits, 0)
      nlogits = nlogits.to(torch.float)
      nlogits = sig(nlogits)
      ntarget = target.to(torch.float)
      # print(nlogits.type(), ntarget.type())
      # print(nlogits, nlogits.shape)
      # print(ntarget, ntarget.shape)

    
      loss = criterion(logits, target)
      if args.auxiliary:
        #nlogits_aux=torch.max(logits_aux)
        nlogits_aux, indices = torch.max(logits_aux, 1)
        # nlogits_aux=torch.unsqueeze(nlogits_aux, 0)
        nlogits_aux = nlogits_aux.to(torch.float)
        nlogits_aux = sig(nlogits_aux)

        loss_aux = criterion(logits_aux, target)

        loss += args.auxiliary_weight*loss_aux
      loss.backward()
      nn.utils.clip_grad_norm(model.parameters(), args.grad_clip)
      optimizer.step()
      # print('nlogits:', nlogits)
      # print('ntarget:', ntarget)
      prec1, prec5 = utils.accuracy(logits, target, topk=(1, 1))
      n = input.size(0)
      objs.update(loss.item(), n)
      top1.update(prec1.item(), n)
      top5.update(prec5.item(), n)
      # break
      #print(step)
      if step % args.report_freq == 0:
        logging.info('train %03d %e %f %f', step, objs.avg, top1.avg, top5.avg)

  return top1.avg, objs.avg


def infer(valid_queue, model, criterion):
  print('validating')
  objs = utils.AvgrageMeter()
  top1 = utils.AvgrageMeter()
  top5 = utils.AvgrageMeter()
  model.eval()

  for step, (input, target) in enumerate(valid_queue):
    # input = Variable(input, volatile=True).cuda()
    # target = Variable(target, volatile=True).cuda()

    with torch.no_grad():
      input = Variable(input).cuda()
      target = Variable(target).cuda()

    logits, _ = model(input)
    #nlogits=torch.max(logits)
    nlogits, indices = torch.max(logits, 1)
    # nlogits=torch.unsqueeze(nlogits, 0)
    nlogits = nlogits.to(torch.float)
    nlogits = sig(nlogits)
    ntarget = target.to(torch.float)
    
    loss = criterion((logits), (target))
    
    prec1, prec5 = utils.accuracy(logits, target, topk=(1, 1))
    n = input.size(0)
    objs.update(loss.item(), n)
    top1.update(prec1.item(), n)
    top5.update(prec5.item(), n)

    if step % args.report_freq == 0:
      logging.info('valid %03d %e %f %f', step, objs.avg, top1.avg, top5.avg)

  return top1.avg, objs.avg


if __name__ == '__main__':
  main() 

