import numpy as np
from models import generator
from natsort import natsorted
import os
from utils import *
import torchaudio
import soundfile as sf
import argparse

USE_CUDA = False


@torch.no_grad()
def enhance_one_track(model, audio_path, saved_dir, cut_len, n_fft=400, hop=100, save_tracks=False):
    name = os.path.split(audio_path)[-1]
    noisy, sr = torchaudio.load(audio_path)
    assert sr == 16000
    if USE_CUDA:
        noisy = noisy.cuda()

    c = torch.sqrt(noisy.size(-1) / torch.sum((noisy ** 2.0), dim=-1))
    noisy = torch.transpose(noisy, 0, 1)
    noisy = torch.transpose(noisy * c, 0, 1)

    length = noisy.size(-1)
    frame_num = int(np.ceil(length / 100))
    padded_len = frame_num * 100
    padding_len = padded_len - length
    noisy = torch.cat([noisy, noisy[:, :padding_len]], dim=-1)
    if padded_len > cut_len:
        batch_size = int(np.ceil(padded_len/cut_len))
        while 100 % batch_size != 0:
            batch_size += 1
        noisy = torch.reshape(noisy, (batch_size, -1))

    if USE_CUDA:
        noisy_spec = torch.stft(noisy, n_fft, hop, window=torch.hamming_window(n_fft).cuda(), onesided=True)
    else:
        noisy_spec = torch.stft(noisy, n_fft, hop, window=torch.hamming_window(n_fft), onesided=True)
    
    noisy_spec = power_compress(noisy_spec).permute(0, 1, 3, 2)
    est_real, est_imag = model(noisy_spec)
    est_real, est_imag = est_real.permute(0, 1, 3, 2), est_imag.permute(0, 1, 3, 2)

    est_spec_uncompress = power_uncompress(est_real, est_imag).squeeze(1)
    if USE_CUDA:
        est_audio = torch.istft(est_spec_uncompress, n_fft, hop, window=torch.hamming_window(n_fft).cuda(),
                            onesided=True)
    else:
        est_audio = torch.istft(est_spec_uncompress, n_fft, hop, window=torch.hamming_window(n_fft),
                            onesided=True)

    est_audio = est_audio / c
    est_audio = torch.flatten(est_audio)[:length].cpu().numpy()
    # assert len(est_audio) == length
    if save_tracks:
        saved_path = os.path.join(saved_dir, name)
        sf.write(saved_path, est_audio, sr)

    return est_audio, length


def evaluation(model_path, noisy_dir, save_tracks, saved_dir):
    n_fft = 400
    if USE_CUDA:
        model = generator.TSCNet(num_channel=64, num_features=n_fft//2+1).cuda()
    else:
        model = generator.TSCNet(num_channel=64, num_features=n_fft//2+1)

    model.load_state_dict((torch.load(model_path)))
    model.eval()

    if not os.path.exists(saved_dir):
        os.mkdir(saved_dir)

    audio_list = os.listdir(noisy_dir)
    audio_list = natsorted(audio_list)
    for audio in audio_list:
        noisy_path = os.path.join(noisy_dir, audio)
        est_audio, length = enhance_one_track(model, noisy_path, saved_dir, 16000*16, n_fft, n_fft//4, save_tracks)


parser = argparse.ArgumentParser()
parser.add_argument("--model_path", type=str, default='./best_ckpt/ckpt_80',
                    help="the path where the model is saved")
parser.add_argument("--test_dir", type=str, default='dir to your VCTK-DEMAND test dataset',
                    help="noisy tracks dir to be enhanced")
parser.add_argument("--save_tracks", type=str, default=True, help="save predicted tracks or not")
parser.add_argument("--save_dir", type=str, default='./saved_tracks_best', help="where enhanced tracks to be saved")

args = parser.parse_args()


if __name__ == '__main__':
    noisy_dir = os.path.join(args.test_dir, 'noisy')
    evaluation(args.model_path, noisy_dir, args.save_tracks, args.save_dir)
