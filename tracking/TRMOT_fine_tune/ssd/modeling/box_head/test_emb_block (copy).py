import torch.nn as nn
import torch.nn.functional as F
import torch

from ssd.utils import box_utils
import math

class Test_emb(nn.Module):
    def __init__(self, cfg, nID):
        """Implement SSD MultiBox Loss.

        Basically, MultiBox loss combines classification loss
         and Smooth L1 regression loss.
        """
        super(Test_emb, self).__init__()
        self.cfg = cfg
        self.neg_pos_ratio = self.cfg.MODEL.NEG_POS_RATIO
        self.emb_scale = math.sqrt(2) * math.log(nID-1)
        self.classifier = nn.Linear(512, nID)
        self.IDLoss = nn.CrossEntropyLoss(ignore_index=-1)

        self.s_c = nn.Parameter(-4.15*torch.ones(1))  # -4.15 #k nn.Parameter將某個tensor轉成可訓練的類型parameter並將這個參數加入到module中,net.parameter()中就會有這個parameter,所以在優化時也會一起優化
        self.s_r = nn.Parameter(-4.85*torch.ones(1))  # -4.85
        self.s_id = nn.Parameter(-2.3*torch.ones(1))  # -2.3

    def forward(self, img_path, confidence, predicted_locations, predicted_ids, labels, gt_locations, gt_ids):
        ####embeding####

        #pos_mask = gt_ids > 0
        pos_mask = labels > 0
        predicted_ids = predicted_ids[pos_mask, :].contiguous()
        predicted_ids = self.emb_scale * F.normalize(predicted_ids)
        gt_ids = gt_ids.unsqueeze(2)[pos_mask, :]

        #confidence 
        #'''new_2020_0212_22:26 
        confidence = confidence[pos_mask, :]
        #print(confidence[..., 1].shape)
        con_mask = confidence[..., 1] > 0.01
        predicted_ids = predicted_ids[con_mask]
        gt_ids = gt_ids[con_mask]
        #'''2020_0212_22:26

        emb_and_gt = torch.cat((predicted_ids, gt_ids.float()), 1)
        #print(emb_and_gt.shape)

        return emb_and_gt.cpu()

