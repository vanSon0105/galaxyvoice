# UVR Audio Separation Integration Research

Date: 2026-08-02

## Decision

Do not import the official Ultimate Vocal Remover GUI application directly into
Galaxy Studio. Use an isolated `python-audio-separator` runtime as the supported
adapter for UVR models, and communicate with it through a small subprocess bridge.

This keeps Galaxy's Python environment stable, gives the app a real CLI/Python
API, supports automatic model downloads, and provides an experimental DirectML
path for the Intel Iris Xe laptop used during development.

## Official UVR repository assessment

The official UVR repository is an excellent end-user application and model hub,
but it is not shaped as an embeddable SDK:

- The latest stable UVR GUI release is v5.6 from September 2023.
- It supports VR Architecture, MDX-Net/MDX23C, and Demucs models.
- Two-stem models normally produce Vocals and Instrumental. Demucs models can
  produce four stems, and some variants produce six stems.
- It exports WAV, FLAC, and MP3 and uses FFmpeg for non-WAV media.
- Its README describes the code as MIT licensed and requests attribution for UVR
  and its model developers.
- The repository has no maintained official headless CLI. Community CLI examples
  exist in issues, but they are not a stable public contract.
- `UVR.py` is a GUI entry point of more than 7,000 lines. It changes the process
  working directory during import and owns global Tk/model/config state.
- `separate.py` exposes separation classes, but their configuration objects are
  assembled from UVR GUI state. Calling these classes directly would couple Galaxy
  to UVR internals and make upgrades brittle.

Conclusion: UVR should remain the upstream model/application reference, not a
module loaded into the Galaxy process.

## Recommended engine adapter

[`python-audio-separator`](https://github.com/karaokenerds/python-audio-separator)
is an MIT-licensed package derived mainly from UVR separation code. It provides:

- A documented CLI and Python `Separator` API.
- Automatic model download and a programmatic model list.
- MDX, VR, MDXC/RoFormer, and Demucs model support.
- Common input/output formats through FFmpeg.
- CPU, NVIDIA CUDA, Apple CoreML, and experimental Windows DirectML options.
- Long-file chunking and multi-model ensembles.

Use a dedicated environment such as:

```text
%LOCALAPPDATA%\GalaxyAIStudio\engines\audio-separator\.venv
%LOCALAPPDATA%\GalaxyAIStudio\models\AudioSeparator
```

Galaxy should launch a bridge script with that environment's Python. The bridge
accepts a JSON job, initializes `Separator`, emits line-delimited JSON progress,
and returns the generated stem paths. The GUI process should not import PyTorch,
ONNX Runtime, or `audio_separator` itself.

Pin the package version in the installer. Do not install it into Galaxy's main
Python because its Torch, ONNX, NumPy, and audio dependencies can conflict with
Whisper, ProPainter, or Python 3.13 packages.

## Device behavior

| Device | Recommended backend | Practical model support |
| --- | --- | --- |
| NVIDIA RTX | CUDA | MDX, VR, MDXC/RoFormer, Demucs |
| Intel/AMD GPU on Windows | DirectML, experimental | MDX ONNX and VR are accelerated |
| Intel Iris Xe | DirectML, experimental | Prefer an MDX `.onnx` fast model |
| CPU | CPU | All supported models, but RoFormer/Demucs can be slow |

Current `python-audio-separator` documentation says DirectML falls back to CPU for
MDXC/RoFormer because of allocator limits, and does not support Demucs because a
required fused LSTM operator is unavailable. The UI must show the resolved device
and fallback instead of merely saying "GPU".

The development machine runs Python 3.13 and has no NVIDIA runtime. A separate
Python 3.10 environment is the conservative choice for DirectML because Microsoft's
published Windows `torch-directml` wheels lag normal PyTorch releases.

## Proposed Galaxy tab

Tab title: `Tach am thanh`

### MVP workflows

1. `Tach giong va nhac`: export both Vocals and Instrumental.
2. `Xoa giong`: export only Instrumental.
3. `Xoa nhac`: export only Vocals.
4. `Tat am thanh video`: remove the video's audio stream with FFmpeg, no AI model.

Input accepts audio or video. Video input is converted to a separation-ready audio
file using Galaxy's bundled FFmpeg. Original media is never overwritten.

### Controls

- Input file and output folder.
- Operation selector for the four MVP workflows.
- Quality preset: `Nhanh`, `Chat luong`, and `Nang cao`.
- Processing device: Auto, CPU, NVIDIA CUDA, Intel/AMD DirectML.
- Output format: WAV or MP3. WAV should be the default working/master format.
- Download/install engine button and visible model download status.
- Process, Cancel, Open Output, and playback controls for Source/Vocals/Instrumental.
- Optional `Ghep vao video` action that replaces the source video's audio with the
  selected stem while copying the original video stream where possible.

Do not expose model segment size, overlap, batch size, or ensemble algorithms in
the initial screen. Put those in an Advanced section after the basic workflow is
stable.

### Presets

- `Nhanh`: one MDX ONNX model. `UVR-MDX-NET-Inst_HQ_5.onnx` is a candidate to
  benchmark because it is compatible with the DirectML path and is included in a
  low-resource preset upstream.
- `Chat luong`: one current RoFormer model. Warn that it will run on CPU on Iris Xe.
- `Nang cao`: four/six stems and ensembles in a later phase.

The exact default model should be pinned only after a small benchmark set covers
songs, dialogue over music, movie clips, and noisy compressed video audio.

## Output contract

Each job should create one project folder without exposing runtime temp files:

```text
exports/<project>/
|-- <project>_vocals.wav
|-- <project>_instrumental.wav
|-- <project>_vocals.mp3          (optional)
|-- <project>_instrumental.mp3    (optional)
|-- <project>_video.mp4           (optional remux)
`-- audio_separation_manifest.json
```

The manifest should record source path, selected operation, package/model version,
model checksum, requested and resolved device, output files, duration, and warnings.
Temporary WAV and chunk files belong under `%LOCALAPPDATA%\GalaxyAIStudio\cache` or
a job-scoped temporary directory and must be removed after success.

## Delivery phases

### Phase 1: engine seam

- Add installer and isolated runtime discovery.
- Add a subprocess bridge and typed options/result objects.
- Implement two-stem WAV separation with CPU and device reporting.
- Add cancellation, cleanup, model caching, manifests, and tests with a fake bridge.

### Phase 2: usable tab

- Build the new tab and save non-secret preferences in `config.json`.
- Accept audio/video, add playback, WAV/MP3 export, and video audio replacement.
- Add the MDX DirectML path and explicit fallback messages for Intel Iris Xe.

### Phase 3: quality and advanced stems

- Benchmark and pin Fast/Quality presets.
- Add Demucs four/six-stem output and RoFormer quality models.
- Add ensembles only after download size, time, and memory estimates are visible.

## Licensing and distribution checks

- Preserve MIT notices for copied or distributed UVR/audio-separator code.
- Credit UVR, its core developers, `python-audio-separator`, and the selected model
  authors in the app and manifest.
- Audit every default model and third-party architecture before bundling or claiming
  commercial-use permission. The UVR code's MIT statement does not automatically
  prove that every third-party model weight has identical terms.
- Download models on demand instead of committing weights to this repository.
- Pin download URLs and verify checksums before execution.

## Primary sources

- [Ultimate Vocal Remover GUI repository and README](https://github.com/Anjok07/ultimatevocalremovergui)
- [UVR v5.6 release](https://github.com/Anjok07/ultimatevocalremovergui/releases/tag/v5.6)
- [UVR GUI source](https://github.com/Anjok07/ultimatevocalremovergui/blob/master/UVR.py)
- [UVR separation implementation](https://github.com/Anjok07/ultimatevocalremovergui/blob/master/separate.py)
- [UVR requirements](https://github.com/Anjok07/ultimatevocalremovergui/blob/master/requirements.txt)
- [`python-audio-separator` repository](https://github.com/karaokenerds/python-audio-separator)
- [`python-audio-separator` dependency and extras declaration](https://github.com/karaokenerds/python-audio-separator/blob/main/pyproject.toml)
- [`python-audio-separator` MIT license](https://github.com/karaokenerds/python-audio-separator/blob/main/LICENSE)
- [PyTorch with DirectML on Windows](https://learn.microsoft.com/windows/ai/directml/pytorch-windows)
- [`torch-directml` package](https://pypi.org/project/torch-directml/)
