import os
encoder_path = os.path.join('code/ravensdr/models/h8l', 'tiny-whisper-encoder-10s_15dB_h8l.hef')
params = VDevice.create_params()
params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
with VDevice(params) as vd:
    m = vd.create_infer_model(encoder_path)
    m.input().set_format_type(FormatType.FLOAT32)
    print('Expected input shape:', m.input().shape)
    print('Expected input bytes:', 4 * 1, end='')
    import numpy as np
    print(' x '.join(str(x) for x in m.input().shape), '=', np.prod(m.input().shape) * 4)