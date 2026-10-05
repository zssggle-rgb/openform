import base64
import hashlib
import html
import json
from importlib.resources import files
from typing import Literal

from openform.activities.schemas import DraftInput


def sample_draft(kind: Literal["quiz", "words", "lab"]) -> DraftInput:
    source = files("openform_contracts").joinpath("examples", kind)
    manifest = json.loads(source.joinpath("manifest.json").read_text(encoding="utf-8"))
    grading = json.loads(source.joinpath("private-grading.json").read_text(encoding="utf-8"))
    config = {key: manifest[key] for key in ("questions", "submissionSchema", "capabilities")}
    controller = files("openform.activities").joinpath("sample.js").read_text(encoding="utf-8")
    script = ("const activityConfig=" + json.dumps(config, ensure_ascii=False).replace("<", "\\u003c") + ";\n" + controller).encode()
    document = ("""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>课堂活动</title><style>
*{box-sizing:border-box}body{margin:0;color:#161823;background:#fff;font:16px/1.7 'PingFang SC','Microsoft YaHei',sans-serif}
main{max-width:720px;margin:auto;padding:24px}h1{font-size:24px}h2{font-size:20px}fieldset{border:1px solid #EAECEF;border-radius:6px;margin:20px 0;padding:16px}
label{display:block;margin:8px 0}input,textarea,select,button{font:inherit}textarea,input[type=number]{width:100%;padding:10px;border:1px solid #777D88;border-radius:4px}
input[type=radio]{margin-right:12px}label:has(input[type=radio]){min-height:56px;padding:10px;background:#F7F8FA;border-radius:4px}
button{min-height:48px;border:1px solid #777D88;border-radius:4px;background:white;padding:8px 16px;cursor:pointer;margin:4px}
button.primary{background:#5B4BCB;color:white;border-color:#5B4BCB}button:disabled{opacity:.55;cursor:default}:focus-visible{outline:2px solid #5B4BCB;outline-offset:3px}
.row{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}.notice{background:#F0EEFF;padding:12px;border-radius:4px;overflow-wrap:anywhere}
@media(max-width:480px){main{padding:12px}.row{grid-template-columns:1fr 1fr}.row button{grid-column:1/-1}}
</style></head><body><main><h1>""" + html.escape(manifest["title"]) + "</h1><p>" + html.escape(manifest["objective"]) + """</p>
<p id="status" class="notice" role="status">正在连接课堂…</p><div id="answers"><div id="questions"></div>
<button id="save" type="button">保存进度</button><button id="read" type="button">读取已保存进度</button>
<button id="submit" class="primary" type="button">提交本次作答</button></div></main><script src="controller.js"></script></body></html>""").encode()
    resources = {"index.html": document, "controller.js": script}
    manifest["assets"] = [{"path": path, "sha256": hashlib.sha256(content).hexdigest(),
                           "mediaType": "text/html" if path.endswith("html") else "text/javascript"} for path, content in resources.items()]
    return DraftInput(manifest=manifest, grading=grading, assets={path: base64.b64encode(content).decode() for path, content in resources.items()}, expected_revision=0)
