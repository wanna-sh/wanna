"""ctypes binding for the parts of stable-diffusion.cpp's C interface (include/stable-diffusion.h) that wanna.sh uses.

The structs mirror the header of the pinned release (engines/sdcpp.py, DEFAULT_TAG) field for field. Every struct is
filled by the library's own *_init function first, so fields wanna.sh doesn't set keep the library's defaults.
`check_layout` confirms after loading that the library reads the fields back as they were written; if a new release
changes the layout, it fails loudly instead of generating with garbled settings.
"""

from __future__ import annotations

import ctypes as C
import os
import sys
from pathlib import Path

c_enum = C.c_int


class sd_tiling_params_t(C.Structure):
    _fields_ = [("enabled", C.c_bool), ("temporal_tiling", C.c_bool), ("tile_size_w", C.c_int),
                ("tile_size_h", C.c_int), ("target_overlap", C.c_float), ("rel_size_w", C.c_float),
                ("rel_size_h", C.c_float), ("extra_tiling_args", C.c_char_p)]


class sd_ctx_params_t(C.Structure):
    _fields_ = [
        ("model_path", C.c_char_p), ("clip_l_path", C.c_char_p), ("clip_g_path", C.c_char_p),
        ("clip_vision_path", C.c_char_p), ("t5xxl_path", C.c_char_p), ("llm_path", C.c_char_p),
        ("llm_vision_path", C.c_char_p), ("diffusion_model_path", C.c_char_p),
        ("high_noise_diffusion_model_path", C.c_char_p), ("uncond_diffusion_model_path", C.c_char_p),
        ("embeddings_connectors_path", C.c_char_p), ("vae_path", C.c_char_p), ("audio_vae_path", C.c_char_p),
        ("audio_encoder_path", C.c_char_p), ("taesd_path", C.c_char_p), ("control_net_path", C.c_char_p),
        ("ip_adapter_path", C.c_char_p), ("motion_module_path", C.c_char_p),
        ("embeddings", C.c_void_p), ("embedding_count", C.c_uint32),
        ("photo_maker_path", C.c_char_p), ("pulid_weights_path", C.c_char_p), ("tensor_type_rules", C.c_char_p),
        ("n_threads", C.c_int), ("wtype", c_enum), ("rng_type", c_enum), ("sampler_rng_type", c_enum),
        ("prediction", c_enum), ("lora_apply_mode", c_enum),
        ("enable_mmap", C.c_bool), ("flash_attn", C.c_bool), ("diffusion_flash_attn", C.c_bool),
        ("tae_preview_only", C.c_bool), ("diffusion_conv_direct", C.c_bool), ("vae_conv_direct", C.c_bool),
        ("force_sdxl_vae_conv_scale", C.c_bool), ("vae_format", c_enum),
        ("max_vram", C.c_char_p), ("disable_prefetch", C.c_bool), ("eager_load", C.c_bool),
        ("backend", C.c_char_p), ("params_backend", C.c_char_p), ("split_mode", C.c_char_p),
        ("auto_fit", C.c_bool), ("rpc_servers", C.c_char_p), ("model_args", C.c_char_p),
        ("disable_segmented_compute", C.c_bool), ("batched_cfg", C.c_bool),
        ("linear_scale", C.c_float), ("attn_scale", C.c_float), ("tokenizer", C.c_char_p),
        ("sage_attn", C.c_bool), ("conditioning_cache_size", C.c_int),
        ("flash_attn_mode", C.c_char_p), ("conv_direct_mode", C.c_char_p),
    ]


class sd_image_t(C.Structure):
    _fields_ = [("width", C.c_uint32), ("height", C.c_uint32), ("channel", C.c_uint32),
                ("data", C.POINTER(C.c_uint8))]


class sd_image_result_t(C.Structure):
    _fields_ = [("image", sd_image_t), ("generation_info", C.c_char_p)]


class sd_image_generation_result_t(C.Structure):
    _fields_ = [("items", C.POINTER(sd_image_result_t)), ("count", C.c_int)]


class sd_image_preprocess_params_t(C.Structure):
    _fields_ = [("rules", C.c_char_p)]


class sd_slg_params_t(C.Structure):
    _fields_ = [("layers", C.POINTER(C.c_int)), ("layer_count", C.c_size_t), ("layer_start", C.c_float),
                ("layer_end", C.c_float), ("scale", C.c_float)]


class sd_guidance_params_t(C.Structure):
    _fields_ = [("txt_cfg", C.c_float), ("img_cfg", C.c_float), ("distilled_guidance", C.c_float),
                ("slg", sd_slg_params_t)]


class sd_sample_params_t(C.Structure):
    _fields_ = [("guidance", sd_guidance_params_t), ("scheduler", c_enum), ("sample_method", c_enum),
                ("sample_steps", C.c_int), ("eta", C.c_float), ("shifted_timestep", C.c_int),
                ("custom_sigmas", C.POINTER(C.c_float)), ("custom_sigmas_count", C.c_int),
                ("flow_shift", C.c_float), ("extra_sample_args", C.c_char_p)]


class sd_pm_params_t(C.Structure):
    _fields_ = [("id_images", C.POINTER(sd_image_t)), ("id_images_count", C.c_int), ("id_embed_path", C.c_char_p),
                ("style_strength", C.c_float)]


class sd_pulid_params_t(C.Structure):
    _fields_ = [("id_embedding_path", C.c_char_p), ("id_weight", C.c_float)]


class sd_cache_params_t(C.Structure):
    _fields_ = [
        ("mode", c_enum), ("reuse_threshold", C.c_float), ("start_percent", C.c_float), ("end_percent", C.c_float),
        ("error_decay_rate", C.c_float), ("use_relative_threshold", C.c_bool), ("reset_error_on_compute", C.c_bool),
        ("Fn_compute_blocks", C.c_int), ("Bn_compute_blocks", C.c_int), ("residual_diff_threshold", C.c_float),
        ("max_warmup_steps", C.c_int), ("max_cached_steps", C.c_int), ("max_continuous_cached_steps", C.c_int),
        ("taylorseer_n_derivatives", C.c_int), ("taylorseer_skip_interval", C.c_int), ("scm_mask", C.c_char_p),
        ("scm_policy_dynamic", C.c_bool), ("spectrum_w", C.c_float), ("spectrum_m", C.c_int),
        ("spectrum_lam", C.c_float), ("spectrum_window_size", C.c_int), ("spectrum_flex_window", C.c_float),
        ("spectrum_warmup_steps", C.c_int), ("spectrum_stop_percent", C.c_float),
    ]


class sd_lora_t(C.Structure):
    _fields_ = [("is_high_noise", C.c_bool), ("multiplier", C.c_float), ("path", C.c_char_p)]


class sd_hires_params_t(C.Structure):
    _fields_ = [("enabled", C.c_bool), ("upscaler", c_enum), ("model_path", C.c_char_p), ("scale", C.c_float),
                ("target_width", C.c_int), ("target_height", C.c_int), ("steps", C.c_int),
                ("denoising_strength", C.c_float), ("upscale_tile_size", C.c_int),
                ("custom_sigmas", C.POINTER(C.c_float)), ("custom_sigmas_count", C.c_int)]


class sd_img_gen_params_t(C.Structure):
    _fields_ = [
        ("loras", C.POINTER(sd_lora_t)), ("lora_count", C.c_uint32), ("prompt", C.c_char_p),
        ("negative_prompt", C.c_char_p), ("clip_skip", C.c_int), ("init_image", sd_image_t),
        ("ref_images", C.POINTER(sd_image_t)), ("ref_images_count", C.c_int), ("ref_image_args", C.c_char_p),
        ("mask_image", sd_image_t), ("width", C.c_int), ("height", C.c_int), ("sample_params", sd_sample_params_t),
        ("strength", C.c_float), ("seed", C.c_int64), ("batch_count", C.c_int), ("control_image", sd_image_t),
        ("control_strength", C.c_float), ("ip_adapter_image", sd_image_t), ("ip_adapter_strength", C.c_float),
        ("pm_params", sd_pm_params_t), ("pulid_params", sd_pulid_params_t), ("vae_tiling_params", sd_tiling_params_t),
        ("cache", sd_cache_params_t), ("hires", sd_hires_params_t), ("qwen_image_layers", C.c_int),
        ("circular_x", C.c_bool), ("circular_y", C.c_bool), ("image_preprocess", sd_image_preprocess_params_t),
    ]


LOG_CB = C.CFUNCTYPE(None, c_enum, C.c_char_p, C.c_void_p)
PROGRESS_CB = C.CFUNCTYPE(None, C.c_int, C.c_int, C.c_float, C.c_void_p)

# enum sample_method_t and scheduler_t: str_to_* return these counts for names they don't know.
SAMPLE_METHOD_COUNT = 21
SCHEDULER_COUNT = 17
# enum sd_cancel_mode_t
SD_CANCEL_ALL = 0
# enum sd_log_level_t
LOG_LEVELS = ["debug", "verbose", "info", "warn", "error"]


def load(lib_dir: str | Path) -> C.CDLL:
    """Load the library from the engine folder, with its ggml libraries beside it."""
    lib_dir = Path(lib_dir)
    from ..engines.sdcpp import LIB

    if sys.platform == "win32":
        os.add_dll_directory(str(lib_dir))
    lib = C.CDLL(str(lib_dir / LIB))
    sig = {
        "sd_set_log_callback": (None, [LOG_CB, C.c_void_p]),
        "sd_set_progress_callback": (None, [PROGRESS_CB, C.c_void_p]),
        "sd_ctx_params_init": (None, [C.POINTER(sd_ctx_params_t)]),
        "new_sd_ctx": (C.c_void_p, [C.POINTER(sd_ctx_params_t)]),
        "free_sd_ctx": (None, [C.c_void_p]),
        "sd_ctx_supports_image_generation": (C.c_bool, [C.c_void_p]),
        "sd_get_model_version_name": (C.c_char_p, [C.c_void_p]),
        "sd_get_default_sample_method": (c_enum, [C.c_void_p]),
        "sd_get_default_scheduler": (c_enum, [C.c_void_p, c_enum]),
        "str_to_sample_method": (c_enum, [C.c_char_p]),
        "str_to_scheduler": (c_enum, [C.c_char_p]),
        "sd_img_gen_params_init": (None, [C.POINTER(sd_img_gen_params_t)]),
        "sd_img_gen_params_to_str": (C.c_void_p, [C.POINTER(sd_img_gen_params_t)]),
        "sd_ctx_params_to_str": (C.c_void_p, [C.POINTER(sd_ctx_params_t)]),
        "generate_image": (C.c_bool, [C.c_void_p, C.POINTER(sd_img_gen_params_t),
                                      C.POINTER(C.POINTER(sd_image_generation_result_t))]),
        "free_sd_image_generation_result": (None, [C.POINTER(sd_image_generation_result_t)]),
        "sd_cancel_generation": (None, [C.c_void_p, c_enum]),
        "sd_get_system_info": (C.c_char_p, []),
        "sd_commit": (C.c_char_p, []),
        "sd_list_devices": (C.c_size_t, [C.c_char_p, C.c_size_t]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return lib


def _owned_str(lib: C.CDLL, ptr: int | None) -> str:
    """Read a char* the library allocated. It isn't freed: freeing it from here could use a different C runtime than
    the library's (on Windows), and these few hundred bytes are read once per model load."""
    return C.string_at(ptr).decode("utf-8", "replace") if ptr else ""


def check_layout(lib: C.CDLL) -> None:
    """Write distinctive values into fields spread across both big structs and confirm the library's own printer reads
    them back. Fails with a clear message if the structs don't match this build of the library."""
    p = sd_img_gen_params_t()
    lib.sd_img_gen_params_init(C.byref(p))
    p.width, p.height, p.seed, p.batch_count = 1234, 777, 987654321, 3
    p.strength = 0.25
    p.sample_params.sample_steps = 37
    p.sample_params.guidance.txt_cfg = 6.25
    p.sample_params.flow_shift = 2.75
    p.qwen_image_layers = 5
    text = _owned_str(lib, lib.sd_img_gen_params_to_str(C.byref(p)))
    want = ["width: 1234", "height: 777", "seed: 987654321", "sample_steps: 37", "txt_cfg: 6.25",
            "flow_shift: 2.75", "strength: 0.25", "qwen_image_layers: 5", "batch_count: 3"]
    missing = [w for w in want if w not in text]

    c = sd_ctx_params_t()
    lib.sd_ctx_params_init(C.byref(c))
    c.vae_path = b"/layout/check/vae.safetensors"
    c.model_args = b"layout_check_arg=1"
    c.conditioning_cache_size = 9
    ctx_text = _owned_str(lib, lib.sd_ctx_params_to_str(C.byref(c)))
    missing += [w for w in ("vae_path: /layout/check/vae.safetensors", "model_args: layout_check_arg=1",
                            "conditioning_cache_size: 9") if w not in ctx_text]
    if missing:
        raise RuntimeError("This stable-diffusion.cpp build doesn't match wanna.sh's binding (values "
                           f"{', '.join(missing)} didn't read back). Use the pinned engine version.")
