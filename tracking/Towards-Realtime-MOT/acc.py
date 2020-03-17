import argparse
import json
import time

import test_ssd  
from models import *
from utils.datasets import JointDataset, collate_fn, ssd_JointDataset, ssd_collate_fn
from utils.utils import *
from utils.log import logger
from models_ssd import build_ssd_model

from ssd.config import cfg

def train(
        cfg,
        data_cfg,
        img_size=(1088,608),
        resume=False,
        epochs=100,
        batch_size=16,
        accumulated_batches=1,
        freeze_backbone=False,
        opt=None,
):
    weights = 'weights' 
    mkdir_if_missing(weights) #k from utils.utils
    #latest = osp.join(weights, 'latest.pt')

    #239
    #latest = osp.join(weights, 'mobilenet_fpn_test_e30_b32_1e-3_5e-4_adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_e60_b32_1e-3_5e-4_adam.pt')
    #230
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e50_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e60_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e70_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e70_1e-3_Adam_2.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e70_1e-3_Adam_8703.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_1024_b32_e70_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e80_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e80_1e-3_Adam_2.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e90_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e90_1e-3_Adam_2.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e100_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e100_1e-3_Adam_2.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e110_1e-3_Adam.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e110_1e-3_Adam_2.pt')

    #new
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e100_1e-3_Adam_new.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e100_1e-3_Adam_loss_test.pt')
    #latest = osp.join(weights, 'mobilenet_fpn_test_512_b32_e130_1e-3_Adam_loss_test_gpu1.pt')

    #1emb
    latest = osp.join(weights, 'epoch_119.pt')



    #m2det
    #latest = osp.join(weights, 'm2det_e30_b32_1e-3_5e-4_Adam.pt')


    torch.backends.cudnn.benchmark = True  # unsuitable for multiscale #k cudnn優化

    # Configure run
    f = open(data_cfg)
    data_config = json.load(f)
    trainset_paths = data_config['train']
    dataset_root = data_config['root']
    f.close()

    # Get dataloader
    dataset = ssd_JointDataset(cfg, dataset_root, trainset_paths, img_size)
    
    with torch.no_grad():
        mAP, R, P = test_ssd.test(cfg, data_cfg, weights=latest, batch_size=cfg.TEST.BATCH_SIZE, img_size=img_size, print_interval=40, nID=dataset.nID)
        #test_ssd.test_emb(cfg, data_cfg, weights=latest, batch_size=cfg.TEST.BATCH_SIZE, img_size=img_size, print_interval=40, nID=dataset.nID)
    



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=30, help='number of epochs')
    parser.add_argument('--batch-size', type=int, default=8, help='size of each image batch')
    parser.add_argument('--accumulated-batches', type=int, default=1, help='number of batches before optimizer step')
    parser.add_argument('--cfg', type=str, default='cfg/yolov3.cfg', help='cfg file path')
    parser.add_argument('--data-cfg', type=str, default='cfg/ccmcpe.json', help='coco.data file path')
    parser.add_argument('--img-size', type=int, default=(416, 416), help='pixels')
    parser.add_argument('--resume', action='store_true', help='resume training flag')
    parser.add_argument('--print-interval', type=int, default=40, help='print interval')
    parser.add_argument('--test-interval', type=int, default=9, help='test interval')
    parser.add_argument('--lr', type=float, default=1e-2, help='init lr')
    parser.add_argument('--unfreeze-bn', action='store_true', help='unfreeze bn')
    opt = parser.parse_args()

    init_seeds()

    #ssd_cfg_path = './vgg_ssd512_voc0712.yaml'
    ssd_cfg_path = './mobilenet_fpn_test_512_bdd100k_E200.yaml'
    #ssd_cfg_path = './vgg_m2det_512.yaml'
    #ssd_cfg_path = './mobilenet_fpn_test_1024.yaml'
    cfg.merge_from_file(ssd_cfg_path)
    cfg.freeze()

    train(
        cfg,
        opt.data_cfg,
        img_size=(cfg.INPUT.IMAGE_SIZE, cfg.INPUT.IMAGE_SIZE),
        resume=opt.resume,
        epochs=cfg.SOLVER.EPOCH,
        batch_size=cfg.SOLVER.BATCH_SIZE,
        accumulated_batches=opt.accumulated_batches,
        opt=opt,
    )
