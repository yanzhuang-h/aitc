from setuptools import setup, Extension
from Cython.Build import cythonize
from Cython.Compiler import Options
import os
import glob
import shutil

# 配置Cython编译选项
Options.docstrings = False
Options.annotate = False

# 目标文件夹
protected_dir = "time_schedule"

# 获取所有需要编译的Python文件
py_files = glob.glob(os.path.join(protected_dir, "*.py"))

# 排除特殊文件
excluded_files = ["__init__.py"]
module_paths = [
    f for f in py_files
    if os.path.basename(f) not in excluded_files
]

# 设置编译选项
extensions = []
for module in module_paths:
    module_name = os.path.splitext(os.path.basename(module))[0]
    extensions.append(
        Extension(
            f"{protected_dir}.{module_name}",  # 保持原始模块路径
            [module],
            extra_compile_args=["-O3"],
            define_macros=[("NPY_NO_DEPRECATED_API", "NPY_1_7_API_VERSION")]
        )
    )

# 编译前清除build目录
build_dir = "build"
if os.path.exists(build_dir):
    shutil.rmtree(build_dir)

# 编译扩展模块
setup(
    name='Protected Modules',
    ext_modules=cythonize(
        extensions,
        nthreads=4,
        compiler_directives={
            'language_level': "3",
            'boundscheck': False,
            'wraparound': False,
            'initializedcheck': False,
            'cdivision': True,
            'nonecheck': False
        },
        build_dir=build_dir
    ),
    script_args=["build_ext", "--inplace"]  # 关键：编译到源文件位置
)

# 清理过程
print("\n清理临时文件...")
for module in module_paths:
    # 删除原始.py文件
    if os.path.exists(module):
        os.remove(module)

    # 删除生成的.c文件
    c_file = module.replace(".py", ".c")
    if os.path.exists(c_file):
        os.remove(c_file)

# 删除空build目录
if os.path.exists(build_dir):
    shutil.rmtree(build_dir)

print("编译完成！原始.py文件已被替换为编译后的二进制文件")