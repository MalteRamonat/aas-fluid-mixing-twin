# Vendored front-end dependencies

| File | Version | Licence | Source |
| --- | --- | --- | --- |
| `vendor/echarts.min.js` | Apache ECharts 5.5.1 | Apache-2.0 (header retained in the file) | `https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js` |

The dashboard loads nothing from a CDN: it has to work on a plant network with no internet
access, and a pinned local copy is also the only way to be sure what is running. To update,
download the new file, note the version here, and check the charts still render.
