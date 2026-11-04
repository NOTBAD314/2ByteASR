---
license: cc-by-nc-4.0
library_name: transformers
pipeline_tag: voice-activity-detection
tags:
- speaker 
- speaker-diarization
- meeting
- wavlm
- wespeaker
- diarizen
- pyannote
- pyannote-audio-pipeline
---

## Overview
This hub features the pre-trained model by [DiariZen](https://github.com/BUTSpeechFIT/DiariZen). The EEND component is built upon WavLM Large and Conformer layers. The model was trained on far-field, single-channel audio from a diverse set of public datasets, including AMI, AISHELL-4, AliMeeting, NOTSOFAR-1, MSDWild, DIHARD3, RAMC, and VoxConverse. 

Then structured pruning at 80% sparsity is applied. After pruning, the number of parameters in WavLM Large is reduced from **316.6M to 63.3M**, and the computational cost (MACs) decreases from **17.8G to 3.8G** per second. When loading this model, please ensure **non-commercial** usage, in accordance with the CC BY-NC 4.0 license.

## Note
This repository contains DiariZen, which supports up to four overlapping speakers for improved diarization performance. Please make sure to pull the most recent code before using the model, as outdated versions may lead to unexpected issues or degraded results. If you prefer to use the original (legacy) model, you can find it [here](https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md).

## Usage
```python
from diarizen.pipelines.inference import DiariZenPipeline

# load pre-trained model
diar_pipeline = DiariZenPipeline.from_pretrained("BUT-FIT/diarizen-wavlm-large-s80-md-v2")
# apply diarization pipeline
diar_results = diar_pipeline('audio.wav')

# print results
for turn, _, speaker in diar_results.itertracks(yield_label=True):
    print(f"start={turn.start:.1f}s stop={turn.end:.1f}s speaker_{speaker}")

# load pre-trained model and save RTTM result
diar_pipeline = DiariZenPipeline.from_pretrained(
        "BUT-FIT/diarizen-wavlm-large-s80-md-v2",
        rttm_out_dir='.'
)
# apply diarization pipeline
diar_results = diar_pipeline('audio.wav', sess_name='session_name')
```

## Results (collar=0s) 
| Dataset       | [Pyannote v3.1](https://github.com/pyannote/pyannote-audio) | DiariZen |
|:---------------|:-----------:|:-----------:|
| AMI           | 22.4      | 13.9 |
| AISHELL-4     | 12.2      | 10.1 |
| AliMeeting    | 24.4      | 10.8 |
| NOTSOFAR-1    | -      | 16.7 |
| MSDWild       | 25.3      | 15.8 | 
| DIHARD3       | 21.7      | 14.5 | 
| RAMC          | 22.2      | 11.0 | 
| VoxConverse   | 11.3      | 9.1 |

## Citation
If you found this work helpful, please consider citing:
```
@inproceedings{han2025leveraging,
  title={Leveraging self-supervised learning for speaker diarization},
  author={Han, Jiangyu and Landini, Federico and Rohdin, Johan and Silnova, Anna and Diez, Mireia and Burget, Luk{\'a}{\v{s}}},
  booktitle={Proc. ICASSP},
  year={2025}
}

@article{han2025fine,
  title={Fine-tune Before Structured Pruning: Towards Compact and Accurate Self-Supervised Models for Speaker Diarization},
  author={Han, Jiangyu and Landini, Federico and Rohdin, Johan and Silnova, Anna and Diez, Mireia and Cernocky, Jan and Burget, Lukas},
  journal={arXiv preprint arXiv:2505.24111},
  year={2025}
}

@article{han2025efficient,
  title={Efficient and Generalizable Speaker Diarization via Structured Pruning of Self-Supervised Models},
  author={Han, Jiangyu and P{\'a}lka, Petr and Delcroix, Marc and Landini, Federico and Rohdin, Johan and Cernock{\`y}, Jan and Burget, Luk{\'a}{\v{s}}},
  journal={arXiv preprint arXiv:2506.18623},
  year={2025}
}
```

## License
- **Source code**: MIT (see the [project’s GitHub repository](https://github.com/BUTSpeechFIT/DiariZen)).
- **Model weights**: CC BY-NC 4.0 (non-commercial).
- Rationale: some training datasets are research-only or non-commercial, so the released weights cannot be used commercially.