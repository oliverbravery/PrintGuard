# Third-party notices

PrintGuard bundles the following third-party software as unmodified binaries. Each is
distributed under its own licence, reproduced or linked below.

MediaMTX and QuickJS-ng are separate programs (mere aggregation - each runs as its own process
or in its own sandbox and is not linked into PrintGuard). FFmpeg, ONNX Runtime, LiteRT and
Wasmtime are shared libraries the hub loads, taken as they come in each project's Python wheel.

The hub also loads native code from the Python packages in the first table. The GPU images, the
desktop apps and the dashboard carry further libraries after it, and the dashboard's typefaces
come last.

| Package | Licence | Native libraries it carries |
|---|---|---|
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause, the text under PyAV above | OpenBLAS |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU | libjpeg, libtiff and FreeType among others |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 OR BSD-3-Clause, the Apache-2.0 text under Wasmtime below | OpenSSL |
| [uvloop](https://github.com/MagicStack/uvloop) | MIT, the text under MediaMTX above | libuv |
| [pydantic-core](https://github.com/pydantic/pydantic-core) | MIT, the text under MediaMTX above | Its own Rust code |
| [paho-mqtt](https://github.com/eclipse-paho/paho.mqtt.python) | [EPL-2.0](https://www.eclipse.org/legal/epl-2.0/) OR BSD-3-Clause | None, and its source is at the link |


## MediaMTX

- Project: https://github.com/bluenviron/mediamtx
- Licence: MIT

```
MIT License

Copyright (c) 2019 aler9

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## QuickJS-ng

Shipped as `printguard/server/runtime/qjs.wasm`, the unmodified `qjs-wasi.wasm` artefact
from the v0.16.1 release
(SHA-256 `055f8d7e811e5ce6244ded7d13885f4e8466ed1fe513fce488ca01c32e1975fd`). PrintGuard runs
it under wasmtime to execute plugin code in a sandbox; it is not linked into PrintGuard.

- Project: https://github.com/quickjs-ng/quickjs
- Licence: MIT

```
MIT License

Copyright (c) 2017-2024 Fabrice Bellard
Copyright (c) 2017-2024 Charlie Gordon
Copyright (c) 2023-2025 Ben Noordhuis
Copyright (c) 2023-2025 Saúl Ibarra Corretgé

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## FFmpeg, through PyAV

The PyAV wheel carries the FFmpeg libraries (libavcodec, libavformat, libavutil, libavdevice,
libavfilter, libswscale and libswresample) and the codec libraries they were built with.
PrintGuard uses them to read camera streams. The libraries report their licence as LGPL
version 3 or later.

- Project: https://ffmpeg.org
- Licence: [LGPL-3.0-or-later](https://www.gnu.org/licenses/lgpl-3.0.html), which adds to the
  [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html)
- Source: https://ffmpeg.org/download.html, built by the scripts at
  https://github.com/PyAV-Org/pyav-ffmpeg

PyAV itself:

- Project: https://github.com/PyAV-Org/PyAV
- Licence: BSD-3-Clause

```
Copyright retained by original committers. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the project nor the names of its contributors may be
      used to endorse or promote products derived from this software without
      specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## ONNX Runtime

- Project: https://github.com/microsoft/onnxruntime
- Licence: MIT

```
MIT License

Copyright (c) Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## LiteRT

- Project: https://github.com/google-ai-edge/LiteRT
- Licence: Apache-2.0, reproduced under Wasmtime below

## Wasmtime

- Project: https://github.com/bytecodealliance/wasmtime
- Licence: Apache-2.0 WITH LLVM-exception

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.


--- LLVM Exceptions to the Apache 2.0 License ----

As an exception, if, as a result of your compiling your source code, portions
of this Software are embedded into an Object form of such source code, you
may redistribute such embedded portions in such Object form without complying
with the conditions of Sections 4(a), 4(b) and 4(d) of the License.

In addition, if you combine or link compiled forms of this Software with
software that is licensed under the GPLv2 ("Combined Software") and if a
court of competent jurisdiction determines that the patent provision (Section
3), the indemnity provision (Section 9) or other Section of the License
conflicts with the conditions of the GPLv2, you may retroactively and
prospectively choose to deem waived or otherwise exclude such Section(s) of
the License, but only in their entirety and only with respect to the Combined
Software.
```

## OpenVINO execution provider

In the `amd64` images, from the `onnxruntime-ep-openvino` wheel, which also carries the OpenVINO,
oneTBB and hwloc libraries the provider loads.

- Project: https://pypi.org/project/onnxruntime-ep-openvino/
- Licence: MIT, as the wheel's metadata gives it and as reproduced under MediaMTX above. The wheel
  carries no licence text for the libraries inside it

## NVIDIA CUDA runtime and TensorRT RTX provider

In the `-nvidia` image only.

The CUDA runtime, from the `nvidia-cuda-runtime-cu12` wheel:

- Project: https://developer.nvidia.com/cuda-zone
- Licence: proprietary, NVIDIA's End User License Agreement, which the wheel ships as
  `License.txt`

The TensorRT RTX provider, from the `onnxruntime-ep-nv-tensorrt-rtx-cu12` wheel, which also
carries the TensorRT RTX libraries:

- Project: https://github.com/NVIDIA/TensorRT-RTX-EP-ABI
- Licence: Apache-2.0, as the wheel's metadata gives it and as reproduced under Wasmtime above.
  The wheel carries no licence text for the TensorRT RTX libraries inside it

## Windows ML and the Windows App SDK

In the Windows app only.

ONNX Runtime with Windows ML, from the `onnxruntime-windowsml` wheel, which also carries
`DirectML.dll`:

- Project: https://onnxruntime.ai
- Licence: MIT, as under ONNX Runtime above

The Windows App SDK projections, from the `wasdk-Microsoft.Windows.AI.MachineLearning` and
`wasdk-Microsoft.Windows.ApplicationModel.DynamicDependency.Bootstrap` wheels, the second of
which carries `Microsoft.WindowsAppRuntime.Bootstrap.dll`:

- Project: https://github.com/pywinrt/pywinrt
- Licence: MIT, as the wheels' metadata gives it. They carry no licence text for the DLL

## CPython

The Python interpreter, inside the desktop apps and the images.

- Project: https://www.python.org
- Licence: [Python Software Foundation License Version 2](https://docs.python.org/3/license.html)

## Desktop app libraries

| Library | In | Licence | Copyright |
|---|---|---|---|
| [pystray](https://github.com/moses-palmer/pystray) | Both apps | [LGPL-3.0-or-later](https://www.gnu.org/licenses/lgpl-3.0.html), which adds to the [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html) | Copyright (C) 2016-2022 Moses Palmér |
| [pywebview](https://github.com/r0x0r/pywebview) | Both apps | BSD-3-Clause, the text under PyAV above | Copyright (c) 2014-2017, Roman Sirokov |
| [desktop-notifier](https://github.com/samschott/desktop-notifier) | Both apps | MIT | Copyright (c) 2021, Sam Schott |
| [platformdirs](https://github.com/tox-dev/platformdirs) | Both apps | MIT | Copyright (c) 2010-202x The platformdirs developers |
| [Python.NET](https://github.com/pythonnet/pythonnet) | Windows app | MIT | Copyright (c) 2006-2021 the contributors of the Python.NET project |
| [clr-loader](https://github.com/pythonnet/clr-loader) | Windows app | MIT | Copyright (c) 2019-2026 Benedikt Reinartz |
| [pywin32](https://github.com/mhammond/pywin32) | Windows app | PSF, as the wheel's metadata gives it | |
| [winrt-runtime and the winrt-Windows-\* projections](https://github.com/pywinrt/pywinrt) | Windows app | MIT | Copyright (c) Microsoft Corporation. All rights reserved. Copyright (c) 2021-2025 David Lechner |
| [pyobjc](https://github.com/ronaldoussoren/pyobjc) core and the Cocoa, Quartz, Security, UniformTypeIdentifiers and WebKit frameworks | macOS app | MIT | Copyright 2002, 2003 - Bill Bumgarner, Ronald Oussoren, Steve Majewski, Lele Gaifax, et.al. Copyright 2003-2025 - Ronald Oussoren |
| [rubicon-objc](https://github.com/beeware/rubicon-objc) | macOS app | BSD-3-Clause, the text under PyAV above | Copyright (c) 2014 Russell Keith-Magee. |
| [bottle](https://github.com/bottlepy/bottle) | Both apps | MIT | Copyright (c) 2009-2025, Marcel Hellkamp. |
| [proxy_tools](https://github.com/jtushman/proxy_tools) | Both apps | MIT, as the wheel's metadata gives it | |
| [bidict](https://github.com/jab/bidict) | Both apps | [MPL-2.0](https://www.mozilla.org/MPL/2.0/), whose source is at the link | Copyright 2009-2026 Joshua Bronson. All rights reserved. |
| [six](https://github.com/benjaminp/six) | Both apps | MIT | Copyright (c) 2010-2024 Benjamin Peterson |

The MIT text is reproduced under MediaMTX above.

## Dashboard JavaScript libraries

Built into the dashboard the hub serves.

| Library | Licence | Copyright |
|---|---|---|
| [React](https://github.com/facebook/react), with react-dom and scheduler | MIT | Copyright (c) Meta Platforms, Inc. and affiliates. |
| [dnd kit](https://github.com/clauderic/dnd-kit) | MIT | Copyright (c) 2021, Claudéric Demers |
| [zustand](https://github.com/pmndrs/zustand) | MIT | Copyright (c) 2019 Paul Henschel |
| [hls.js](https://github.com/video-dev/hls.js) | Apache-2.0 | Copyright (c) 2017 Dailymotion (http://www.dailymotion.com) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | MPL-2.0 OR Apache-2.0 | |
| [marked](https://github.com/markedjs/marked) | MIT | Copyright (c) 2018+, MarkedJS (https://github.com/markedjs/). Copyright (c) 2011-2018, Christopher Jeffrey (https://github.com/chjj/) |
| [gcode-preview](https://github.com/remcoder/gcode-preview) | MIT | Copyright (c) 2017 Remco Veldkamp |
| [three.js](https://github.com/mrdoob/three.js) | MIT | Copyright © 2010-2023 three.js authors |
| [lil-gui](https://lil-gui.georgealways.com) | MIT | Copyright (c) 2019 George Michael Brower |
| [fflate](https://github.com/101arrowz/fflate) | MIT | Copyright (c) 2026 Arjun Barrett |
| [Lucide](https://github.com/lucide-icons/lucide) | ISC | Copyright (c) 2026 Lucide Icons and Contributors. Copyright (c) 2013-present Cole Bemis |
| [react-image-crop](https://github.com/dominictobias/react-image-crop) | ISC | Copyright (c) 2015, Dominic Tobias (https://github.com/dominictobias) |
| [Acorn](https://github.com/acornjs/acorn), with acorn-walk | MIT | Copyright (C) 2012-2022 by various contributors (see AUTHORS) |
| [parse5](https://github.com/inikulin/parse5) | MIT | Copyright (c) 2013-2019 Ivan Nikulin (ifaaan@gmail.com, https://github.com/inikulin) |
| [entities](https://github.com/fb55/entities) 8.0.0, used by parse5 | BSD-2-Clause | Copyright (c) Felix Böhm |
| [tslib](https://github.com/microsoft/tslib), used by dnd kit | 0BSD | Copyright (c) Microsoft Corporation. |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | MIT | Copyright (c) Tailwind Labs, Inc. |

The MIT text is reproduced under MediaMTX above and the Apache-2.0 text under Wasmtime. The ISC,
BSD-2-Clause and 0BSD texts follow.

ISC, for Lucide and react-image-crop, with the copyright lines in the table above:

```
Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

BSD-2-Clause, for entities:

```
Copyright (c) Felix Böhm
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

THIS IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

0BSD, for tslib:

```
Copyright (c) Microsoft Corporation.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

## Saira, Saira Condensed and Chivo Mono

The dashboard's typefaces, shipped as the Latin and Latin Extended WOFF2 files from the
[Fontsource](https://fontsource.org) 5.3.0 packages in `web/src/fonts/`, so the dashboard
loads them from the hub.

- Projects: https://github.com/Omnibus-Type/Saira and https://github.com/Omnibus-Type/Chivo
- Licence: OFL-1.1

```
Saira: Copyright 2020 The Saira Project Authors (https://github.com/Omnibus-Type/Saira)
Saira Condensed: Copyright 2016 The Saira Project Authors (omnibus.type@gmail.com), with reserved font name "Saira".
Chivo Mono: Copyright 2018 The Chivo Project Authors (https://github.com/Omnibus-Type/Chivo)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```
