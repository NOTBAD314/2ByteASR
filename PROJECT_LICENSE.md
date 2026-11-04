# 2ByteASR project license

SPDX-License-Identifier: GPL-3.0-only

Effective for the project-owned code in version **0.2.6-test.3** and subsequent versions unless lawfully changed by the relevant rightsholders. The adoption date is 2026-09-30.

The author licenses the original 2ByteASR application code they have authority to license under **GNU General Public License version 3 only**. You may use, study, copy, modify and convey that code, including commercial use and distribution for a price, under the unmodified English [LICENSE](LICENSE). There is no project-specific restriction on sale, hosting, support, advertising, donations or bundling. The only additional permission is the Remotion/GSAP permission below. The appendix in the standard license contains an example referring to later versions; that example is not this project's grant.

This grant covers the author's original Python application and worker code, original renderer components, build/install scripts and original website code. Existing copyright and contributor notices remain intact. The grant does not assert ownership of copied code or contributions whose authority has not been established. New original contributions are accepted under GPL-3.0-only as described in [CONTRIBUTING.md](CONTRIBUTING.md); copyright is not assigned to the author.

Separately licensed content includes `third_party/`, dependency packages and binaries, `tools/`, `wheels/`, fonts, downloaded model code/weights/tokenizers, third-party skills/templates and artwork, and material carrying its own license notice. In particular the GIMP bridge retains its existing GPL-3.0-or-later notice. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [component evidence](licenses/COMPONENTS.md), and [model terms](licenses/MODELS.md). This separation does not resolve an incompatible linked or combined work. Pending permissions for game reference images, PSD/XCF source artwork and unverified contributions are not granted by this document.

Official versions are provided free of charge; GPL permits others to distribute copies for a price. Preserve applicable notices and identify modifications under GPL. Do not misrepresent a modified version as the official author's work; this statement adds no approval, reporting, revenue-sharing or watermark condition.

Private modifications need not be published or contributed upstream. GPL does not add the AGPL network-use source-disclosure trigger. Ordinary subtitle, video and image outputs do not become GPL merely because this software produced them; outputs containing protected code, original font files or other protected resources require assessment of that content and its own terms.

When conveying covered object code, provide exact Corresponding Source and fulfill the applicable GPL conditions. [SOURCE_DELIVERY.md](SOURCE_DELIVERY.md) describes this version's local attachments and outstanding third-party gaps. It does not claim an online release or a complete source offer. Prior valid Apache or other grants are not revoked retroactively. Historical test.2 packages retain their original license and separate identities.

## Additional permission under GNU GPL version 3 section 7 (Remotion and GSAP)

Granted 2026-10-11 by the author for the project-owned code covered by the grant above, in version 0.6.5 and in every earlier or later version that contains that code. For 0.6.5 this explicitly includes build r9 (source fingerprint `88dd50773fcad681c6bf2c73c28a53aa6749b4424c40019165bad3d48f66fbfb`), the release source commit `a74c6d645858fa5cbacc80fda7c213f74267a198` (tag `v0.6.5`) and `2ByteASR-Setup-0.6.5.exe` (SHA-256 `16904292c22016ae9dfef823c2cff6c7b5083bb56c31cc505a5f4805e65eb4ab`), whose bundled notices predate this grant; the release also carries `2ByteASR-0.6.5-GPL-Additional-Permission.txt`. The 0.7.0 release carries `2ByteASR-0.7.0-GPL-Additional-Permission.txt`, which names its build, release source commits and installer SHA-256 values.

If you modify this Program, or any covered work, by linking or combining it with Remotion (the `remotion` and `@remotion/*` packages, including the `@remotion/compositor-*` native binaries) or GSAP (the `gsap` package), in the versions recorded in that release's `renderer/package-lock.json` (for 0.6.5 and 0.7.0: Remotion 4.0.513 and GSAP 3.15.0), or modified versions of them, containing parts covered by the terms of their own licenses, the licensor of this Program grants you additional permission to convey the resulting work. Corresponding Source for a non-source form of such a combination shall include the source code for the parts of Remotion and GSAP used, to the extent their licenses make it available, as well as that of the covered work.

This permission:

- applies only to code whose copyright the author holds. It does not apply to `third_party/`, to other GPL-licensed components such as FFmpeg, x264, x265, mpv or the GIMP bridge, or to anyone else's code, except where a contributor grants the same permission: on 2026-10-13 CODE-A-DUCK granted it for the code contributed in PR #2 (`renderer/populate-fonts.mjs` and the font-copy lines in `renderer/service.mjs`);
- grants no rights in Remotion or GSAP. Their use, copying and distribution stay governed by their own licenses and conditions: the [Remotion License](licenses/materials/remotion/4.0.513/LICENSE.md) (for example, organisations that do not qualify for its free license need a Remotion Company License) and the [GSAP Standard "No Charge" License](licenses/materials/gsap/3.15.0/standard-license.txt);
- may be removed from modified versions, as GPLv3 section 7 allows.

The English GNU text is the legal license. Explanations in Chinese, English or Japanese are summaries, not amendments. This adoption is not a representation that the entire current dependency combination has received legal clearance.
## Optional AI model increment (2026-10-06)

Original DiariZen/VibeVoice adapters, task transport, attribution and UI remain under the existing GPL-3.0-only grant and 0.2.6-test.3 boundary. Fixed upstream DiariZen and VibeVoice code retains MIT notices; their weights are independently licensed. DiariZen v2 weights are CC-BY-NC-4.0 with additional complete upstream research and compatibility wording; WeSpeaker and PLDA retain CC-BY-4.0. Both pinned VibeVoice-ASR-Streaming checkpoints are marked MIT. See [the originals and exact revisions](licenses/optional-models/README.md).

Independent acquisition, subprocess execution and local acknowledgment do not resolve formal integration or redistribution compatibility. No extra restriction is added to GPL-covered code and no model license is automatically assigned to user subtitle outputs. Existing third-party permissions and exact-source gaps remain open.

