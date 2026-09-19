# 📔 我的日记本

一个用 Python + Streamlit 做的简单日记记录工具。

## 功能

- ✍️ 写日记（标题、心情、内容）
- 📷 贴图片（支持多张，写完预览）
- 📖 查看历史日记，支持关键词搜索
- 🗑️ 删除日记（同时清理图片文件）

## 安装和运行

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 启动应用：
```bash
streamlit run app.py
```

3. 浏览器会自动打开，地址是 `http://localhost:8501`

## 项目结构

```
diary-app/
├── app.py            # 主程序
├── requirements.txt  # 依赖
├── diary.json        # 日记数据（运行后自动生成）
├── images/           # 图片存储目录（运行后自动生成）
└── README.md
```

## .gitignore 建议

```
diary.json
images/
```

## 后续可以加的功能

- [ ] 导出日记为 PDF 或 TXT
- [ ] 按心情筛选日记
- [ ] 日记数量统计图表
- [ ] 密码保护
