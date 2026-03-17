# Python

版本： 3.10

Python 有两种执行模式（对应 API 的 language 参数）： `python` 和 `pytest` 。 这两个语言都没有编译过程，直接执行指令 `python <filename>` 或 `pytest <filename>` 。

沙盒默认的 pip 包及其版本的列表可以在[这个文件](https://github.com/bytedance/SandboxFusion/blob/main/runtime/python/requirements.txt)中找到。 Python 运行环境位于 conda 环境 `sandbox-runtime` 中（依赖通过 uv 安装）。默认使用 CPU 版 torch；如需 CUDA 支持，请运行 `install-gpu-runtime.sh`。

沙盒环境预先下载了 `nltk` 包的 `punkt` 和 `stopwords` 两个模块，用于部分评估集的运行。
