# NetUpDown (Python 3.13)

一个基于 Flask 的断点续传网站：
- 用户注册/登录后才能使用；
- 支持前端分片上传（断点续传）；
- 支持文件下载 Range（可续传）；
- 下载目录时自动打包为 ZIP。

## 运行

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

访问：`http://127.0.0.1:8000`

## 测试

```bash
pytest -q
```
