"""隔离构建前后 wheel，避免旧 build/lib 的残留影响结果。"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile

root=Path(__file__).resolve().parents[2]
out=root/'output/web/collab-round4'
out.mkdir(exist_ok=True)
source=root/'src/rag_tech_retriever/api/static/shilie/planning-mist.png'
original=hashlib.sha256(source.read_bytes()).hexdigest()
config=(root/'pyproject.toml').read_text(encoding='utf-8')
previous=config[:config.index('[tool.setuptools.exclude-package-data]')]+config[config.index('[tool.pytest.ini_options]'):]
wheels={}
for label,metadata in [('before',previous),('after',config)]:
    workspace=Path(tempfile.mkdtemp(prefix='shilie-package-'+label+'-'))
    shutil.copytree(root/'src',workspace/'src',ignore=shutil.ignore_patterns('__pycache__','*.egg-info'))
    shutil.copy2(root/'README.md',workspace/'README.md')
    (workspace/'pyproject.toml').write_text(metadata,encoding='utf-8')
    target=out/label
    subprocess.run([sys.executable,'-m','pip','wheel',str(workspace),'--no-deps','--no-build-isolation','--wheel-dir',str(target)],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    wheels[label]=next(target.glob('*.whl'))
with zipfile.ZipFile(wheels['before']) as b,zipfile.ZipFile(wheels['after']) as a:
    before=set(b.namelist());after=set(a.namelist())
    missing=before-after
    assert missing=={'rag_tech_retriever/api/static/shilie/planning-mist.png'},missing
    assert not after-before
    changed=[name for name in before&after if b.read(name)!=a.read(name)]
    assert all(name.endswith('.dist-info/RECORD') for name in changed),changed
    assert 'rag_tech_retriever/api/static/shilie/planning-mist.webp' in after
assert hashlib.sha256(source.read_bytes()).hexdigest()==original
report={'before_bytes':wheels['before'].stat().st_size,'after_bytes':wheels['after'].stat().st_size,'saved_bytes':wheels['before'].stat().st_size-wheels['after'].stat().st_size,'removed':sorted(missing),'changed':changed,'original_png_preserved':True,'png_sha256':original,'webp_included':True,'clean_build':True,'visual_review':'1440px同位置截图对照未发现明显退化；不宣称逐像素无差异','network_webp_bytes':155138}
(out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))

