# PSD adapter

`cover-psd.cjs` bundles ag-psd 31.0.2 (MIT), pako and base64-js. Source:
https://github.com/Agamnentzar/ag-psd . It is used with raw RGBA data, without
node-canvas or installation scripts. Entry source: `scripts/cover_psd_adapter.cjs`.

Build with esbuild: `esbuild scripts/cover_psd_adapter.cjs --bundle --platform=node --target=node18 --outfile=third_party/cover-psd.cjs --minify`.
Resolve `ag-psd` at the pinned version above. Separate license files accompany
this bundle. RGB/8 horizontal text is the supported local writing subset.
External PSDs are edited by the official Photopea engine, not roundtripped
through this compatibility adapter.
