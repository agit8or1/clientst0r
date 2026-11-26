# Vendored third-party files

Everything the browser loads is served from this folder. No template, stylesheet or script loads from a CDN, Google
Fonts or another host (`core/tests/test_no_cdn.py`). Each npm file below was taken from the registry tarball and the
tarball was checked against the registry's `dist.shasum` and `dist.integrity` (sha512) before extracting. Files are
unmodified. To upgrade: download the new tarball, verify it the same way, replace the files, update this table and the
template references.

The libraries added earlier (Bootstrap 5.3.0, Font Awesome 6.5.1, DataTables 1.13.7, Select2 4.1.0-rc.0 and its
Bootstrap 5 theme 1.3.0, Leaflet 1.9.4, jQuery 3.7.0) keep their version folders, licences and SHA-256 list in
`core/tests/test_vendored_libraries.py`. Quill 2.0.3 lives in `quill/2.0.3/` (licence beside it).

| Library | Version | Licence | Source | Files in this folder |
|---|---|---|---|---|
| Chart.js | 4.4.1 | MIT | https://registry.npmjs.org/chart.js/-/chart.js-4.4.1.tgz (`dist/chart.umd.js`, already minified) | `chartjs/chart.umd.js` `74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3`; `chartjs/chart.umd.js.map` `0dc6bf22c3ec9b0769936b67f09a15edd2de08c07c1298db2fb7c803a8d29cbc`; `chartjs/LICENSE` |
| SortableJS | 1.15.2 | MIT | https://registry.npmjs.org/sortablejs/-/sortablejs-1.15.2.tgz | `sortablejs/Sortable.min.js` `ca68430703c4f5960e90735867c6e94d29b5a3de37107d8100e5a301007e9e6e`; `sortablejs/LICENSE` |
| jsvectormap | 1.6.0 | MIT | https://registry.npmjs.org/jsvectormap/-/jsvectormap-1.6.0.tgz | `jsvectormap/jsvectormap.min.js` `e3979d3e3dc42d5de35167faaac2722de730187a909ca4a98b058e8ed6b18f7b`; `jsvectormap/jsvectormap.min.css` `d6c1c7d40b28cdbda3955c0de4071cd8831f93a33b4672a5d7b7fcf3c00fc33c`; `jsvectormap/world.js` (`dist/maps/world.js`) `de3c2c21cf63bdd95a4cfc477a566a4b189579daeb26157e8ecb101000224edd`; `jsvectormap/LICENSE` |
| html5-qrcode | 2.3.8 | Apache-2.0 | https://registry.npmjs.org/html5-qrcode/-/html5-qrcode-2.3.8.tgz (the template loaded the unversioned unpkg URL, i.e. latest, which is 2.3.8) | `html5-qrcode/html5-qrcode.min.js` `660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e`; `html5-qrcode/LICENSE` |
| Inter | 4.1 | SIL OFL 1.1 | https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip (zip sha256 `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`; files from `web/`) | `inter/InterVariable.woff2` `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3`; `inter/InterVariable-Italic.woff2` `e564f652916db6c139570fefb9524a77c4d48f30c92928de9db19b6b5c7a262a`; `inter/LICENSE.txt` `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a`; `inter/inter.css` (our `@font-face`, `font-display: swap`, weight 100 900) |

Notes: rack detail used SortableJS 1.15.0 and the other pages 1.15.2; all use 1.15.2 now (same `new Sortable(el, opts)` API).
Chart.js loads `chart.umd.js` (the registry file name; the CDN served a re-minified copy as `chart.umd.min.js`).
