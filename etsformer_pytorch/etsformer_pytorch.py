import torch
import torch.nn.functional as F
from torch import nn, einsum

from einops import rearrange, repeat
from einops.layers.torch import Rearrange

# helper functions

def exists(val):
    return val is not None

# classes

def FeedForward(dim, mult = 4, dropout = 0.):
    return nn.Sequential(
        nn.Linear(dim, dim * mult),
        nn.Sigmoid(),
        nn.Dropout(dropout),
        nn.Linear(dim * mult, dim),
        nn.Dropout(dropout)
    )

def InputEmbedding(time_features, model_dim, kernel = 3, dropout = 0.):
    return nn.Sequential(
        Rearrange('b n d -> b d n'),
        nn.Conv1d(time_features, model_dim, kernel = kernel, padding = kernel // 2),
        nn.Dropout(dropout),
        Rearrange('b d n -> b n d'),
    )

class NaiveMHESA(nn.Module):
    def __init__(
        self,
        *,
        dim,
        heads = 8,
        dim_head = 32,
        dropout = 0.
    ):
        super().__init__()
        inner_dim = heads * dim_head
        self.heads = heads
        self.initial_state = nn.Parameter(torch.randn(heads, dim_head))

        self.dropout = nn.Dropout(dropout)
        self.alpha = nn.Parameter(torch.randn(heads))

        self.project_in = nn.Linear(dim, inner_dim)
        self.project_out = nn.Linear(inner_dim, dim)

    def forward(self, x):
        # in appendix A.1 - Algorithm 2

        b, n, d, h, device = *x.shape, self.heads, x.device

        # linear project in

        x = self.project_in(x)

        # split out heads

        x = rearrange(x, 'b n (h d) -> b h n d', h = h)

        # temporal difference

        x = torch.cat((
            repeat(self.initial_state, 'h d -> b h 1 d', b = b),
            x
        ), dim = -2)

        x = x[:, :, 1:] - x[:, :, :-1]

        # prepare exponential alpha

        alpha = self.alpha.sigmoid()
        alpha = rearrange(alpha, 'h -> h 1')

        # arange == powers

        arange = torch.arange(n, device = device)
        weights = alpha * (1 - alpha) ** torch.flip(arange, dims = (0,))

        weights = repeat(weights, '... l -> ... t l', t = n)
        indices = repeat(arange, 'l -> h t l', h = h, t = n)

        indices = (indices - rearrange(arange + 1, 't -> 1 t 1')) % n

        weights = weights.gather(-1, indices)
        weights = self.dropout(weights)

        # causal

        weights = weights.tril()

        # multiply

        output = einsum('b h n d, h m n -> b h m d', x, weights)

        # get initial state contribution

        init_weight = (1 - alpha) ** (arange + 1)
        init_output = rearrange(init_weight, 'h n -> h n 1') * rearrange(self.initial_state, 'h d -> h 1 d')

        output = output + init_output

        # merge heads

        output = rearrange(output, 'b h n d -> b n (h d)')
        return self.project_out(output)

class FrequencyAttention(nn.Module):
    def __init__(
        self,
        *,
        K = 4,
        dropout = 0.
    ):
        super().__init__()
        self.K = K
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        freqs = torch.fft.rfft(x, dim = 1)

        # get amplitudes

        amp = freqs.abs()
        amp = self.dropout(amp)

        # topk amplitudes - for seasonality, branded as attention

        _, topk_amp_indices = amp.topk(k = self.K, dim = 1)

        # scatter back

        topk_freqs = torch.zeros_like(freqs).scatter(1, topk_amp_indices, freqs)

        # inverse fft

        return torch.fft.irfft(topk_freqs, dim = 1)

# main class

class ETSFormer(nn.Module):
    def __init__(
        self,
        *,
        time_features,
        model_dim,
        heads = 8,
        dim_head = 32,
        K = 4
    ):
        super().__init__()

    def forward(self, x):
        return x
