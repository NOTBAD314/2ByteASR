# Rust FFmpeg splitter

The goal is to use this in Remotion to achieve the following:

- Have the FFmpeg CLI
- Be able to use FFmpeg functions in Rust
- Have no duplicate code
- Precompile it for all platforms
- Be lightweight

## Instructions

```
node clean.mjs
node compile-ffmpeg.mjs
node generate-bindings.mjs
node zip.mjs
```

## Relation to Remotion repository

By running the above instructions on a macOS Apple Silicon machine, and by running it in a CircleCI pipeline (free tier works as long as this repo is kept open source) and downloading the artifacts, we obtain 7 zip files:

```
aarch64-unknown-linux-gnu.gz
x86_64-apple-darwin.gz
x86_64-unknown-linux-gnu.gz
aarch64-apple-darwin.gz
aarch64-unknown-linux-musl.gz
x86_64-pc-windows-gnu.gz
x86_64-unknown-linux-musl.gz
```

These 7 files are added to the fork of the [`rust-ffmpeg-sys`](https://github.com/remotion-dev/rust-ffmpeg-sys) crate in the `zips` folder. Create your own fork off Remotion if necessary.

Once committed and pushed to GitHub, the commit ID is copied and added to the [`rust-ffmpeg`](https://github.com/remotion-dev/rust-ffmpeg) crate in the [`Cargo.toml`] file. Fork this repository as well if necessary and change the repository name to your fork.

Once this is committed and pushed to GitHub, the main Remotion repository references the `rust-ffmpeg` repository in the [`Cargo.toml`](https://github.com/remotion-dev/remotion/blob/main/packages/Cargo.toml#L22) file.
