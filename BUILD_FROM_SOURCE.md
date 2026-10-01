# Build the 0.5.0 paired source on Windows

Extract 2ByteASR-Source-0.5.0.zip and 2ByteASR-ThirdParty-Materials-0.5.0.zip into the same NEW directory. SOURCE_SNAPSHOT.json records every selected file, the dirty original worktree/base commit, exact build-input paths and source SHA. This is a full internal paired source tree, distinct from the limited public source candidate.

Use the recorded BUILD_ENVIRONMENT.json (Python 3.10.11; existing PyInstaller 6.22.2, PySide6/Shiboken 6.9.2 and av 17.1.0), locked Python/npm/model inputs and Inno Setup 6. Do not upgrade dependencies or substitute same-named media libraries. The adopted product chain remains unchanged; the isolated native-AAC experiment is not an input.

~~~powershell
$buildPython = 'C:\path\to\build-env\Scripts\python.exe'
& $buildPython scripts/rebuild_source_attachment.py --output tmp/rebuild-0.5.0-r1
& .\scripts\build_frozen_setup.ps1 -PayloadDir .\tmp\rebuild-0.5.0-r1\payload\2ByteASR -ReleaseDir .\tmp\setup-0.5.0-r1
~~~

The rebuild verifier refuses existing output directories and mismatched input bytes. It reads application inputs solely from this fixed tree; it may reuse the documented unchanged build environment. Fresh PyInstaller work/output directories prevent old application binaries being reused. The renderer is re-bundled from the fixed source in an isolated cache during this round's actual rendering checks, rather than importing a historical generated bundle.

AppId/application identity and user-data/model/project paths stay unchanged. Factory settings come from DEFAULT_SETTINGS; personal settings, keys and raw task records are not application inputs. Use isolated QA profiles for validation.

Bundled prebuilt dependencies are not corresponding source for those binaries. See licenses/SOURCES.md and licenses/GPL3_ROUTE.md for exact remaining permissions/materials. This application rebuild is not a claim of bit-identical signing, all native libraries rebuilt, a clean-machine full model matrix, or public-release clearance. The limited public-source candidate has its own exclusions and missing build inputs; see SOURCE_ONLY_SCOPE.md.

## macOS desktop source boundary

The current macOS increment targets native Apple Silicon arm64 desktop use. Follow the [macOS build and validation guide](docs/deployment/macos-experimental.zh-CN.md) for its separate runtime, model preparation, native inputs and actual validation status. Windows paired-source receipts do not establish Mac bundle, GUI, preview, export, signing or hardware success. A source or workflow entry is not a downloadable Mac application; only an actual validated bundle may have an installation archive.

The project-specific Docker/Linux deployment recipe, dedicated headless CLI and deployment tests are retired from current release selection. Historical test evidence is preserved internally. Shared desktop model preparation and required third-party media recipes remain; they do not provide a current Docker product entry.
