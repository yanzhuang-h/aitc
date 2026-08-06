"""Local smoke test for Qwen3-0.6B.

Run from this directory:
    python .\main.py --prompt "Explain traffic flow and queue length."

The model files are expected under:
    infra/model/qwen/Qwen3-0.6B/
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_PATH = Path(__file__).parent / "Qwen3-0.6B"
QWEN3_THINK_END_TOKEN_ID = 151668
DEFAULT_PROMPT = "Please briefly explain the relationship between traffic flow and queue length."


def check_environment() -> None:
    torch_version = tuple(int(part) for part in torch.__version__.split("+")[0].split(".")[:2])
    numpy_major = int(numpy.__version__.split(".")[0])
    if torch_version < (2, 4):
        raise RuntimeError(
            f"Qwen3 local loading requires torch >= 2.4, but found {torch.__version__}. "
            "Install torch==2.4.1 with the CUDA wheel that matches this environment."
        )
    if numpy_major >= 2:
        raise RuntimeError(
            f"This PyTorch wheel is not compatible with numpy {numpy.__version__}. "
            "Use numpy==1.26.4 for the aitc environment."
        )
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model directory does not exist: {MODEL_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Qwen3-0.6B smoke test.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--thinking", action="store_true", help="Enable Qwen3 thinking mode.")
    return parser.parse_args()


def build_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are a traffic control data analysis assistant."},
        {"role": "user", "content": prompt},
    ]


def split_qwen3_output(output_ids: Sequence[int], tokenizer) -> tuple[str, str]:
    try:
        index = len(output_ids) - list(reversed(output_ids)).index(QWEN3_THINK_END_TOKEN_ID)
    except ValueError:
        index = 0
    thinking = tokenizer.decode(output_ids[:index], skip_special_tokens=True).strip()
    content = tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip()
    return thinking, content


def main() -> None:
    args = parse_args()
    check_environment()

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype="auto",
        device_map="auto",
        local_files_only=True,
    )

    text = tokenizer.apply_chat_template(
        build_messages(args.prompt),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=args.thinking,
    )
    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    generate_kwargs = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": True,
        "top_k": 20,
    }
    if args.thinking:
        generate_kwargs.update({"temperature": 0.6, "top_p": 0.95})
    else:
        generate_kwargs.update({"temperature": 0.7, "top_p": 0.8})

    with torch.inference_mode():
        generated_ids = model.generate(**inputs, **generate_kwargs)

    output_ids = generated_ids[0][inputs.input_ids.shape[1] :].tolist()
    thinking, content = split_qwen3_output(output_ids, tokenizer)
    if thinking:
        print("thinking content:")
        print(thinking)
        print()
    print("content:")
    print(content)


if __name__ == "__main__":
    main()
