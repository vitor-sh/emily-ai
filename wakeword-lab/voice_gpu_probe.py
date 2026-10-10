"""Small GPU probe for a fresh subprocess; prints only GPU-related diagnostics."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

def probe():
    result = dict(python=sys.version.split()[0],executable=sys.executable,
                  environment={k:os.environ.get(k) for k in ['CUDA_VISIBLE_DEVICES','NVIDIA_VISIBLE_DEVICES',
                    'LD_LIBRARY_PATH','PYTORCH_NVML_BASED_CUDA_CHECK']})
    try:
        p = subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],
                           capture_output=True,text=True,timeout=15)
        result['nvidia_smi']=dict(returncode=p.returncode,stdout=p.stdout.strip(),stderr=p.stderr.strip())
    except (OSError,subprocess.TimeoutExpired) as error:
        result['nvidia_smi']=dict(error=str(error))
    try:
        driver=ctypes.CDLL('libcuda.so.1')
        driver.cuInit.argtypes=[ctypes.c_uint];driver.cuInit.restype=ctypes.c_int
        code=driver.cuInit(0)
        result['driver_init_code']=code
        name=ctypes.c_char_p()
        driver.cuGetErrorName.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_char_p)]
        driver.cuGetErrorName(code,ctypes.byref(name))
        result['driver_init_name']=name.value.decode() if name.value else None
        count=ctypes.c_int()
        result['driver_device_count_code']=driver.cuDeviceGetCount(ctypes.byref(count))
        result['driver_device_count']=count.value
    except (OSError,AttributeError) as error:
        result['driver_error']=str(error)
    try:
        import torch
        result.update(torch_version=torch.__version__,torch_cuda_build=torch.version.cuda,
                      cuda_available=torch.cuda.is_available())
        try:
            torch.cuda.init()
            result['torch_gpu_name']=torch.cuda.get_device_name(0)
            # Initialization alone doesn't verify the CUDA runtime can execute a kernel.
            result['kernel_test']=float((torch.ones(4,device='cuda')*2).sum().item())
        except Exception as error:
            result['torch_init_error']=f'{type(error).__name__}: {error}'
    except ImportError as error:
        result['torch_import_error']=str(error)
    try:
        result['loaded_driver_paths']=sorted({line.split()[-1] for line in Path('/proc/self/maps').read_text().splitlines()
                                             if 'libcuda.so' in line and line.split()[-1].startswith('/')})
    except OSError:
        pass
    return result

if __name__=='__main__':
    result=probe()
    encoded=json.dumps(result,ensure_ascii=False,indent=2)
    Path(__file__).with_name('gpu-diagnostics.json').write_text(encoded)
    print(encoded)
    raise SystemExit(0 if result.get('kernel_test')==8. else 1)
