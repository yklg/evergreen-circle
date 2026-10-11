#!/usr/bin/env python3
"""使用 fpdf2 生成简单的项目介绍 PDF"""
import sys
from pathlib import Path
from fpdf import FPDF
import markdown2

class ChinesePDF(FPDF):
    """支持中文的 PDF 类"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 使用系统自带中文字体 (fpdf2 新 API)
        self.add_font(fname='/System/Library/Fonts/STHeiti Medium.ttc')
        self.set_font('STHeiti Medium', '', 11)

    def header(self):
        self.set_font('STHeiti Medium', '', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, '常青圈 EvergreenCircle - 项目介绍', 0, 1, 'C')
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font('STHeiti Medium', '', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'第 {self.page_no()} 页', 0, 0, 'C')


def md_to_sections(md_path: Path) -> list[dict]:
    """将 Markdown 解析为结构化章节"""
    content = md_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    sections = []
    current_section = None
    current_content = []

    for line in lines:
        # 检测标题
        if line.startswith('# ') or line.startswith('## '):
            # 保存上一个章节
            if current_section:
                sections.append({
                    'title': current_section,
                    'content': '\n'.join(current_content)
                })
            # 开始新章节
            current_section = line.lstrip('# ').strip()
            current_content = []
        elif line.startswith('### ') or line.startswith('#### '):
            # 子标题作为内容的一部分
            current_content.append(line)
        else:
            current_content.append(line)

    # 保存最后一个章节
    if current_section:
        sections.append({
            'title': current_section,
            'content': '\n'.join(current_content)
        })

    return sections


def clean_markdown(text: str) -> str:
    """清理 Markdown 格式标记"""
    # 移除粗体/斜体标记
    text = text.replace('**', '').replace('*', '')
    # 移除代码标记
    text = text.replace('`', '')
    # 移除链接但保留文本
    import re
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 移除图片
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)
    return text


def generate_pdf(md_path: Path, output_path: Path):
    """生成 PDF"""
    print(f"📖 读取 Markdown: {md_path}")
    sections = md_to_sections(md_path)

    print(f"📝 解析到 {len(sections)} 个章节")

    pdf = ChinesePDF()
    pdf.set_auto_page_break(True)
    pdf.set_margins(20, 25, 20)

    # 封面页
    pdf.add_page()
    pdf.set_font('STHeiti', 'B', 28)
    pdf.set_text_color(22, 119, 255)  # 蓝色
    pdf.cell(0, 20, '常青圈 EvergreenCircle', 0, 1, 'C')
    pdf.ln(5)

    pdf.set_font('STHeiti', '', 18)
    pdf.set_text_color(51, 51, 51)
    pdf.cell(0, 15, '15分钟生活圈智能体检与规划助手', 0, 1, 'C')
    pdf.ln(10)

    pdf.set_font('STHeiti', '', 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, '2026 上海开源软件应用创新大赛 · 百度地图命题一', 0, 1, 'C')
    pdf.ln(5)
    pdf.cell(0, 10, 'AGPL-3.0 开源许可证', 0, 1, 'C')
    pdf.ln(10)

    pdf.set_font('STHeiti', '', 10)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, '最后更新：2026-10-11 | 版本：v0.7', 0, 1, 'C')

    # 内容页
    for i, section in enumerate(sections, 1):
        pdf.add_page()

        # 章节标题
        pdf.set_font('STHeiti', 'B', 18)
        pdf.set_text_color(22, 119, 255)
        pdf.cell(0, 12, section['title'], 0, 1, 'L')
        pdf.ln(3)

        # 章节内容
        pdf.set_font('STHeiti', '', 11)
        pdf.set_text_color(51, 51, 51)

        content = clean_markdown(section['content'])
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 跳过表格和代码块的复杂格式
            if line.startswith('|') or line.startswith('```'):
                continue

            # 列表项
            if line.startswith('- ') or line.startswith('* '):
                pdf.set_text_color(51, 51, 51)
                pdf.multi_cell(0, 7, '• ' + line[2:], 0, 1)
            # 引用块
            elif line.startswith('> '):
                pdf.set_text_color(85, 85, 85)
                pdf.set_font('STHeiti', 'I', 11)
                pdf.multi_cell(0, 7, line[2:], 0, 1)
                pdf.set_font('STHeiti', '', 11)
            # 普通段落
            else:
                # 限制单行长度，避免溢出
                if len(line) > 80:
                    words = line.split(' ')
                    current_line = ''
                    for word in words:
                        if len(current_line + word) > 80:
                            pdf.multi_cell(0, 7, current_line, 0, 1)
                            current_line = word + ' '
                        else:
                            current_line += word + ' '
                    if current_line:
                        pdf.multi_cell(0, 7, current_line, 0, 1)
                else:
                    pdf.multi_cell(0, 7, line, 0, 1)

            pdf.ln(1)

    pdf.output(str(output_path))
    print(f"✅ PDF 已生成: {output_path}")
    print(f"📊 文件大小: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"📄 总页数: {pdf.page_no()}")


if __name__ == '__main__':
    root = Path(__file__).parent.parent
    md_file = root / 'docs' / '常青圈_项目介绍.md'
    pdf_file = root / 'docs' / '常青圈_项目介绍.pdf'

    if not md_file.exists():
        print(f"❌ 找不到 Markdown 文件: {md_file}")
        sys.exit(1)

    generate_pdf(md_file, pdf_file)
