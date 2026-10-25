# 课表转日历 · PDF → ICS

一个无需注册的响应式网站/PWA MVP：上传学校教务系统导出的中文课程表 PDF，核对识别结果和学期日期，下载可导入手机日历的 `.ics` 文件。

## 本地运行

需要 Python 3.11 或更高版本。项目的核心服务只依赖文本层 PDF 解析库：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

浏览器打开 <http://127.0.0.1:8787>。也可以使用 `python server.py --host 0.0.0.0 --port 8787` 监听其他网卡。

Windows 小白也可以双击项目根目录的 [`启动课表转换工具.cmd`](启动课表转换工具.cmd)。首次使用前仍需安装 Python 和 `requirements.txt` 中的依赖。

如果页面显示 **Failed to fetch**，通常是后端没有启动，或是直接双击了 `index.html`。请关闭该页面，双击上面的 `.bat` 文件，等待浏览器打开 `http://127.0.0.1:8787` 后再上传 PDF；页面现在也会显示具体提示并自动重试连接。

## 发布成别人点开即用的链接（Render）

项目已附带 [`Dockerfile`](Dockerfile) 和 [`render.yaml`](render.yaml)，可以部署到 Render。免费方案可能在一段时间无人访问后休眠，第一次打开需要等待几十秒；正式长期使用可以选择付费实例。

1. 在 GitHub 注册账号，新建一个仓库，把本项目所有文件上传进去（不要上传含个人信息的 PDF 或生成的 ICS）。
2. 注册 Render，选择 **New → Web Service → Connect a repository**，选中该 GitHub 仓库。
3. Render 会自动识别 `Dockerfile`；确认健康检查地址为 `/healthz`，点击 **Deploy**。
4. 部署成功后会得到类似 `https://course-calendar-xxxx.onrender.com` 的网址，把这个网址发给同学即可。

部署前建议把服务名改成自己的名称，并在 Render 的设置中限制上传大小、开启 HTTPS（Render 默认提供 HTTPS）。如果需要 OCR，还要在 Docker 镜像中额外安装 Tesseract 和 `chi_sim` 语言包；基础文本型 PDF 无需这些依赖。

## 使用流程

1. 在学校教务系统下载“学期总课程表”PDF，拖入上传区域。
2. 在课程预览表中核对并修改名称、星期、节次、周次、地点、教师和课程类型。
3. 选择学期第 1 周的周一日期。PDF 通常只有“第几周”，程序不会猜测日期。
4. 确认时区（默认 `Asia/Shanghai`），点击“生成 ICS 文件”。
5. 打开下载的文件导入系统日历。

没有具体星期/时间/地点的“其他课程”会生成整周日历事项，不会被擅自安排到某个时段。

## 导入日历

- **iPhone/iPad**：在“文件”或 Safari 中打开 `.ics`，选择“添加全部”，再选择目标日历。
- **Android/Google 日历**：在电脑打开 Google 日历网页，进入“设置 → 导入和导出 → 导入”，选择 ICS 和目标日历。
- **Outlook**：进入日历，选择“添加日历 → 从文件上传”，选择 ICS 并确认。

## PDF 解析和 OCR

首选 `pdfminer.six` 读取文本层，并按表格坐标识别星期。支持 `1-2周,4-13周`、`7-14周`、单周/双周等周次表达式、连续节次和跨页单元格。

节次时间表保存在项目根目录的 [`period_times.json`](period_times.json) 中，可按学校校历直接修改后重启服务；课程只保存节次编号，导出时读取该配置。

扫描型 PDF 会尝试 OCR。要启用 OCR：

```powershell
pip install -r requirements-ocr.txt
```

另外需要安装 Tesseract OCR 可执行程序和 `chi_sim`（简体中文）语言包。OCR 结果会在页面上明确标记为“需要人工核对”；如果依赖未安装，界面会给出清晰的安装提示。无法可靠识别表格结构时，程序拒绝导出，避免生成错误日历。

## API

- `GET /healthz`：健康检查。
- `POST /api/parse`：`multipart/form-data` 字段 `file`，返回课程和全天提醒 JSON。
- `POST /api/generate`：提交 `courses`、`reminders`、`week1_start`（必须为周一）和 `timezone`，返回 ICS 字符串及事件统计。

服务只在内存中处理上传内容，不保存 PDF、姓名、学号或课程日志；上传大小限制为 10 MB。正式部署时请使用 HTTPS 反向代理（例如 Caddy/Nginx），并限制访问日志和磁盘临时目录权限。

## 测试

先运行 `python -m pip install -r requirements-test.txt` 安装测试依赖，再运行 `python -B -m unittest discover -s tests -v`。

测试包含合成文本型 PDF 到 ICS、真实 HTTP 上传边界、输入校验、日历格式和启动检查。手机导入、浏览器交互与实际学校 PDF 的人工验收清单见 [tests/MANUAL.md](tests/MANUAL.md)。

## 已知限制

- 不同学校的 PDF 模板差异很大；上传后务必核对预览表。
- 学期第 1 周日期通常不在课表 PDF 中，必须由用户确认。
- OCR 需要外部 Tesseract 和中文语言包，且比文本层解析更需要人工复核。
- 当前只提供 `Asia/Shanghai` 和 `UTC` 两个时区选项。
