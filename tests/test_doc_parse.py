"""
测试 .doc 文件解析功能
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.parsing.parser import DocumentParser


def test_doc_parsing():
    """测试 .doc 文件解析"""
    print("=" * 60)
    print("测试 .doc 文件解析功能")
    print("=" * 60)

    parser = DocumentParser()

    # 检查是否有 .doc 测试文件
    test_files = [f for f in os.listdir(".") if f.endswith(".doc")]

    if not test_files:
        print("\n⚠️  当前目录没有找到 .doc 文件")
        print("请上传一个 .doc 文件到项目目录，或手动指定路径")
        print("\n示例命令:")
        print("  python test_doc_parse.py path/to/your/file.doc")
        return

    for doc_file in test_files:
        print(f"\n📄 测试文件: {doc_file}")
        print("-" * 60)

        try:
            # 解析文件
            result = parser.parse_file(doc_file)

            print("✅ 解析成功!")
            print(f"   文件类型: {result.file_type}")
            print(f"   文件大小: {result.metadata.get('file_size', 'unknown')} bytes")
            print(f"   条款数量: {len(result.clauses)}")
            print("\n📝 内容预览 (前500字):")
            print("-" * 60)
            print(result.full_text[:500])
            print("-" * 60)

            if len(result.full_text) > 500:
                print("... (内容已截断)")

            print("\n✅ 文件解析测试通过!")

        except Exception as e:
            print(f"❌ 解析失败: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    # 如果提供了命令行参数，使用指定的文件
    if len(sys.argv) > 1:
        doc_file = sys.argv[1]
        if os.path.exists(doc_file):
            print(f"📄 测试指定文件: {doc_file}")
            from src.parsing.parser import DocumentParser

            parser = DocumentParser()
            try:
                result = parser.parse_file(doc_file)
                print(f"✅ 解析成功! 提取了 {len(result.full_text)} 字符")
                print("\n内容预览:")
                print(result.full_text[:500])
            except Exception as e:
                print(f"❌ 解析失败: {e}")
                import traceback

                traceback.print_exc()
        else:
            print(f"❌ 文件不存在: {doc_file}")
    else:
        test_doc_parsing()
