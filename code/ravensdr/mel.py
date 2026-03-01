# Mel spectrogram utilities for Hailo Whisper inference
# Ported from whisper-hailo-8l-fastapi

import os
from functools import lru_cache

import numpy as np
import torch
import torch.nn.functional as F

SAMPLE_RATE = 16000
N_FFT = 400
HOP_LENGTH = 160
CHUNK_LENGTH_S = 10  # Hailo encoder expects 10-second chunks
N_SAMPLES = CHUNK_LENGTH_S * SAMPLE_RATE  # 160,000 samples
N_FRAMES = N_SAMPLES // HOP_LENGTH  # 1000 frames

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def pad_or_trim(array, length=N_SAMPLES, axis=-1):
    """Pad or trim audio array to exactly `length` samples."""
    if torch.is_tensor(array):
        if array.shape[axis] > length:
            array = array.index_select(
                dim=axis, index=torch.arange(length, device=array.device)
            )
        if array.shape[axis] < length:
            pad_widths = [(0, 0)] * array.ndim
            pad_widths[axis] = (0, length - array.shape[axis])
            array = F.pad(array, [p for sizes in pad_widths[::-1] for p in sizes])
    else:
        if array.shape[axis] > length:
            array = array.take(indices=range(length), axis=axis)
        if array.shape[axis] < length:
            pad_widths = [(0, 0)] * array.ndim
            pad_widths[axis] = (0, length - array.shape[axis])
            array = np.pad(array, pad_widths)
    return array


@lru_cache(maxsize=None)
def mel_filters(device, n_mels=80):
    """Load pre-computed mel filterbank from mel_filters.npz."""
    filters_path = os.path.join(MODELS_DIR, "mel_filters.npz")
    with np.load(filters_path, allow_pickle=False) as f:
        return torch.from_numpy(f[f"mel_{n_mels}"]).to(device)


def log_mel_spectrogram(audio, n_mels=80, device=None):
    """
    Compute log-mel spectrogram from audio waveform.

    Parameters
    ----------
    audio : np.ndarray or torch.Tensor
        Audio waveform at 16kHz, float32
    n_mels : int
        Number of mel bands (80 for whisper-tiny)
    device : torch.device, optional
        Device to compute on

    Returns
    -------
    torch.Tensor, shape (n_mels, n_frames)
    """
    if not torch.is_tensor(audio):
        audio = torch.from_numpy(audio)

    if device is not None:
        audio = audio.to(device)

    window = torch.hann_window(N_FFT).to(audio.device)
    stft = torch.stft(audio, N_FFT, HOP_LENGTH, window=window, return_complex=True)
    magnitudes = stft[..., :-1].abs() ** 2

    filters = mel_filters(audio.device, n_mels)
    mel_spec = filters @ magnitudes

    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec
