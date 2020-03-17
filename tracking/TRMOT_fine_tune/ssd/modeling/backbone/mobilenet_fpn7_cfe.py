from torch import nn
import torch.nn.functional as F
import torch

from ssd.modeling import registry
from ssd.utils.model_zoo import load_state_dict_from_url

model_urls = {
    'mobilenet_v2': 'https://download.pytorch.org/models/mobilenet_v2-b0353104.pth',
}

class CFE(nn.Module):
    def __init__(self, inp):
        super(CFE, self).__init__()
        inp_h = round(inp/2)
        self.reduce = nn.Conv2d(inp, inp_h, kernel_size=1, stride=1, padding=0, bias=False)
        self.conv_left = nn.ModuleList([
            nn.Conv2d(inp_h, inp_h, kernel_size=(7,1), padding=(3,0), groups=inp_h, bias=False),
            nn.BatchNorm2d(inp_h),
            nn.ReLU6(inplace=True),
            nn.Conv2d(inp_h, inp_h, kernel_size=(1,7), padding=(0,3), groups=inp_h, bias=False),
            nn.BatchNorm2d(inp_h),
            nn.ReLU6(inplace=True)
        ])
        self.conv_right = nn.ModuleList([
            nn.Conv2d(inp_h, inp_h, kernel_size=(1,7), padding=(0,3), groups=inp_h, bias=False),
            nn.BatchNorm2d(inp_h),
            nn.ReLU6(inplace=True),
            nn.Conv2d(inp_h, inp_h, kernel_size=(7,1), padding=(3,0), groups=inp_h, bias=False),
            nn.BatchNorm2d(inp_h),
            nn.ReLU6(inplace=True)
        ])
        self.smooth = ConvBNReLU(inp, inp, kernel_size=1, stride=1)
        
    def forward(self, x):
        
        x_ = self.reduce(x)
        
        for i in range(len(self.conv_left)):
            if i==0:
                left = self.conv_left[i](x_)
            else:
                left = self.conv_left[i](left)
                
        for i in range(len(self.conv_right)):
            if i==0:
                right = self.conv_right[i](x_)
            else:
                right = self.conv_right[i](right)
                
        out = self.smooth(torch.cat([left,right],1))
                
        return x + out


class ConvBNReLU(nn.Sequential):
    def __init__(self, in_planes, out_planes, kernel_size=3, stride=1, groups=1):
        padding = (kernel_size - 1) // 2
        super(ConvBNReLU, self).__init__(
            nn.Conv2d(in_planes, out_planes, kernel_size, stride, padding, groups=groups, bias=False),
            nn.BatchNorm2d(out_planes),
            nn.ReLU6(inplace=True)
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


class MobileNetV2_fpn7_cfe(nn.Module):
    def __init__(self, width_mult=1.0, inverted_residual_setting=None):
        super(MobileNetV2_fpn7_cfe, self).__init__()
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
            InvertedResidual(1280, 512, 2, 1),
            InvertedResidual(512, 256, 2, 1),
            InvertedResidual(256, 256, 2, 1),
            InvertedResidual(256, 256, 2, 1),
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

        self.cfe0 = CFE(256)
        self.cfe1 = CFE(256)

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
        
        s5 = self.smooth4(s5)
        s4 = self.smooth4(s4)
        s3 = self.smooth3(s3)
        s2 = self.smooth2(s2)
        s1 = self.smooth1(s1)
        s0 = self.smooth0(s0)

        s0 = self.cfe0(s0)
        s1 = self.cfe1(s1)
        
        return s0,s1,s2,s3,s4,s5,s6

@registry.BACKBONES.register('mobilenet_v2_fpn7_cfe')
def mobilenet_v2_fpn7_cfe(cfg, pretrained=True):
    model = MobileNetV2_fpn7_cfe()
    if pretrained:
        model.load_state_dict(load_state_dict_from_url(model_urls['mobilenet_v2']), strict=False)
    return model
