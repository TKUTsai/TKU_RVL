import sys
import numpy as np

from torch import nn
import torch.nn.functional as F
import torch

from ssd.modeling import registry
from ssd.utils.model_zoo import load_state_dict_from_url

model_urls = {
    'mobilenet_v2': 'https://download.pytorch.org/models/mobilenet_v2-b0353104.pth',
}

def check_tensor_value(tensor, mode='tf'):
    if(mode == 'tf'):
        print(tensor.permute(0, 2, 3, 1).shape)
        print(tensor.permute(0, 2, 3, 1))
    else:
        print(tensor.shape)
        print(tensor)

    sys.exit()

class PrintLayer(nn.Module):
    def __init__(self, mode='tf'):
        super(PrintLayer, self).__init__()
        self.mode = mode
    
    def forward(self, x):
        # Do your print / debug stuff here
        # print(x.running_mean)
        if(self.mode == 'tf'):
            print(x.permute(0, 2, 3, 1).shape)
            print(x.permute(0, 2, 3, 1))
        else:
            print(x.shape)
            print(x)
        
        # return x
        sys.exit()

class ConvBNReLU(nn.Sequential):
    def __init__(self, in_planes, out_planes, kernel_size=3, stride=1, groups=1):
        padding = (kernel_size - 1) // 2
        super(ConvBNReLU, self).__init__(
            nn.Conv2d(in_planes, out_planes, kernel_size, stride, padding, groups=groups, bias=False),
            # PrintLayer(),
            nn.BatchNorm2d(out_planes),
            nn.ReLU6(inplace=True),
            # PrintLayer(),
        )

class MobileBlock(nn.Sequential):
    def __init__(self, in_planes, out_planes, kernel_size=3, stride=1, groups=1):
        padding = (kernel_size - 1) // 2
        super(MobileBlock, self).__init__(
            nn.Conv2d(in_planes, out_planes, 3, 1, 1, groups=in_planes, bias=False),
            nn.BatchNorm2d(out_planes),
            nn.ReLU6(inplace=True),
            nn.Conv2d(out_planes, out_planes, 1, 1, 0, groups=1, bias=False),
            nn.BatchNorm2d(out_planes),
        )

class MixConv(nn.Module):
    def __init__(self, inp, oup, stride, expand_ratio):
        super(MixConv, self).__init__()
        self.stride = stride
        assert stride in [1, 2]

        hidden_dim = int(round(inp * expand_ratio))//4
        self.conv1 = ConvBNReLU(inp, hidden_dim, kernel_size=1)
        self.conv3x3 = ConvBNReLU(hidden_dim, hidden_dim, kernel_size=3, stride=stride, groups=hidden_dim)
        self.conv5x5 = ConvBNReLU(hidden_dim, hidden_dim, kernel_size=5, stride=stride, groups=hidden_dim)
        self.conv7x7 = ConvBNReLU(hidden_dim, hidden_dim, kernel_size=7, stride=stride, groups=hidden_dim)
        self.conv9x9 = ConvBNReLU(hidden_dim, hidden_dim, kernel_size=9, stride=stride, groups=hidden_dim)
        self.conv_linear = ConvBNReLU(hidden_dim*4, oup, kernel_size=1)
        
    def forward(self, x):
        x = self.conv1(x)
        conv1 = self.conv3x3(x)
        conv2 = self.conv5x5(x)
        conv3 = self.conv7x7(x)
        conv4 = self.conv9x9(x)
        x = torch.cat([conv1,conv2,conv3,conv4],1)
        x = self.conv_linear(x)
        
        return x      

class InvertedResidual(nn.Module):
    def __init__(self, inp, oup, stride, expand_ratio):
        super(InvertedResidual, self).__init__()
        self.stride = stride
        assert stride in [1, 2]

        hidden_dim = int(round(inp * expand_ratio))
        self.use_res_connect = self.stride == 1 and inp == oup

        layers = []
        if expand_ratio != 1:
            # pw
            layers.append(ConvBNReLU(inp, hidden_dim, kernel_size=1))
        layers.extend([
            # dw
            ConvBNReLU(hidden_dim, hidden_dim, stride=stride, groups=hidden_dim),
            # pw-linear
            nn.Conv2d(hidden_dim, oup, 1, 1, 0, bias=False),
            nn.BatchNorm2d(oup),
        ])
        self.conv = nn.Sequential(*layers)

    def forward(self, x):
        if self.use_res_connect:
            return x + self.conv(x)
        else:
            return self.conv(x)


class MobileNetV2_fpn6_mixconv(nn.Module):
    def __init__(self, width_mult=1.0, inverted_residual_setting=None):
        super(MobileNetV2_fpn6_mixconv, self).__init__()
        block = InvertedResidual
        input_channel = 32
        last_channel = 1280        
        
        if inverted_residual_setting is None:
            inverted_residual_setting = [
                # t, c, n, s
                [1, 16, 1, 1],
                [6, 24, 2, 2],
                [6, 32, 3, 2],
                [6, 64, 4, 2],
                [6, 96, 3, 1],
                [6, 160, 3, 2],
                [6, 320, 1, 1],
            ]

        # only check the first element, assuming user knows t,c,n,s are required
        if len(inverted_residual_setting) == 0 or len(inverted_residual_setting[0]) != 4:
            raise ValueError("inverted_residual_setting should be non-empty "
                             "or a 4-element list, got {}".format(inverted_residual_setting))

        # building first layer
        input_channel = int(input_channel * width_mult)
        self.last_channel = int(last_channel * max(1.0, width_mult))
        features = [ConvBNReLU(3, input_channel, stride=2)]
        # building inverted residual blocks
        for t, c, n, s in inverted_residual_setting:
            output_channel = int(c * width_mult)
            for i in range(n):
                stride = s if i == 0 else 1
                features.append(block(input_channel, output_channel, stride, expand_ratio=t))
                input_channel = output_channel
        # building last several layers
        features.append(ConvBNReLU(input_channel, self.last_channel, kernel_size=1))
        # make it nn.Sequential
        self.features = nn.Sequential(*features)
        self.extras = nn.ModuleList([
            MixConv(1280,512,2,1),
            MixConv(512,256,2,1),
            MixConv(256,256,2,1),
            MixConv(256,256,2,1),
        ])

        self.reduce3 = nn.Conv2d(512, 256, kernel_size=1, stride=1, padding=0)
        self.reduce2 = nn.Conv2d(1280, 256, kernel_size=1, stride=1, padding=0)
        self.reduce1 = nn.Conv2d(96, 256, kernel_size=1, stride=1, padding=0)
        self.reduce0 = nn.Conv2d(32, 256, kernel_size=1, stride=1, padding=0)
        
        self.smooth5 = MobileBlock(256,256)
        self.smooth4 = MobileBlock(256,256)
        self.smooth3 = MobileBlock(256,256)
        self.smooth2 = MobileBlock(256,256)
        self.smooth1 = MobileBlock(256,256)
        self.smooth0 = MobileBlock(256,256)
        
        self.reset_parameters()

    def reset_parameters(self):
        # weight initialization
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out')
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.zeros_(m.bias)
                
    def _upsample_add(self, x, y):
        _,_,H,W = y.size()
        return F.interpolate(x, size=(H,W), mode='nearest') + y

    def forward(self, x):
        features = []
        for i in range(7):
            x = self.features[i](x)
        # check_tensor_value(x)
        features.append(x)
        for i in range(7,14):
            x = self.features[i](x)
        features.append(x)

        for i in range(14, len(self.features)):
            x = self.features[i](x)
        features.append(x)

        for i in range(len(self.extras)):
            x = self.extras[i](x)
            features.append(x)

        s6 = features[6]
        s5 = self._upsample_add(s6,features[5])
        s4 = self._upsample_add(s5,features[4])
        s3 = self._upsample_add(s4,self.reduce3(features[3]))
        s2 = self._upsample_add(s3,self.reduce2(features[2]))
        s1 = self._upsample_add(s2,self.reduce1(features[1]))
        s0 = self._upsample_add(s1,self.reduce0(features[0]))
        
        s5 = self.smooth5(s5)
        s4 = self.smooth4(s4)
        s3 = self.smooth3(s3)
        s2 = self.smooth2(s2)
        s1 = self.smooth1(s1)
        s0 = self.smooth0(s0)

        return s0,s1,s2,s3,s4,s5

@registry.BACKBONES.register('mobilenet_v2_fpn6_mixconv')
def mobilenet_v2_fpn6_mixconv(cfg, pretrained=True):
    model = MobileNetV2_fpn6_mixconv()
    if pretrained:
        model.load_state_dict(load_state_dict_from_url(model_urls['mobilenet_v2']), strict=False)
    return model
