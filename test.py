import os
import sys,re
from pathlib import Path


import LangSegment
LangSegment.setfilters(["zh","en","ja"])

def num2text(t,lang="zh"):
    if lang=='zh':
        return t.replace('1','一').replace('2','二').replace('3','三').replace('4','四').replace('5','五').replace('6','六').replace('7','七').replace('8','八').replace('9','九').replace('0','零')
    return t.replace('1',' one ').replace('2',' two ').replace('3',' three ').replace('4',' four ').replace('5',' five ').replace('6',' six ').replace('7','seven').replace('8',' eight ').replace('9',' nine ').replace('0',' zero ')

# 按行区分中英
# 按行区分中英
def split_text(text_list):
    result=[]
    for text in text_list:
        text=text.replace('[uv_break]','<en>[uv_break]</en>').replace('[laugh]','<en>[laugh]</en>')
        langlist=LangSegment.getTexts(text)
        length=len(langlist)
        for i,t in enumerate(langlist):
            # 当前是控制符，则插入到前一个           
            
            if len(result)>0 and re.match(r'^[\s\,\.]*?\[(uv_break|laugh)\][\s\,\.]*$',t['text']) is not None:
                result[-1]+=t['text']
            else:
                result.append(num2text(t['text'],t['lang']))
    return result


print(split_text(["你好啊,各位123456,[uv_break]我的 english 123456, 朋友[laugh],hello my world","[laugh]你是我的enlish朋友呀,[uv_break],难道不是吗？"]))


exit()

import torch
import torch._dynamo
torch._dynamo.config.suppress_errors = True
torch._dynamo.config.cache_size_limit = 64
torch._dynamo.config.suppress_errors = True
torch.set_float32_matmul_precision('high')
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
VERSION='0.6'

def get_executable_path():
    # 这个函数会返回可执行文件所在的目录
    if getattr(sys, 'frozen', False):
        # 如果程序是被“冻结”打包的，使用这个路径
        return Path(sys.executable).parent.as_posix()
    else:
        return Path.cwd().as_posix()

ROOT_DIR=get_executable_path()

MODEL_DIR_PATH=Path(ROOT_DIR+"/models")
MODEL_DIR_PATH.mkdir(parents=True, exist_ok=True)
MODEL_DIR=MODEL_DIR_PATH.as_posix()

WAVS_DIR_PATH=Path(ROOT_DIR+"/static/wavs")
WAVS_DIR_PATH.mkdir(parents=True, exist_ok=True)
WAVS_DIR=WAVS_DIR_PATH.as_posix()

LOGS_DIR_PATH=Path(ROOT_DIR+"/logs")
LOGS_DIR_PATH.mkdir(parents=True, exist_ok=True)
LOGS_DIR=LOGS_DIR_PATH.as_posix()

import soundfile as sf
import ChatTTS
import datetime
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
load_dotenv()


import hashlib,webbrowser
from modelscope import snapshot_download
import numpy as np
import time
# 读取 .env 变量
WEB_ADDRESS = os.getenv('WEB_ADDRESS', '127.0.0.1:9966')

# 默认从 modelscope 下载模型,如果想从huggingface下载模型，请将以下3行注释掉
CHATTTS_DIR = snapshot_download('pzc163/chatTTS',cache_dir=MODEL_DIR)
chat = ChatTTS.Chat()
chat.load_models(source="local",local_path=CHATTTS_DIR,compile=True if os.getenv('compile','true').lower()!='false' else False)

# 如果希望从 huggingface.co下载模型，将以下注释删掉。将上方3行内容注释掉
#os.environ['HF_HUB_CACHE']=MODEL_DIR
#os.environ['HF_ASSETS_CACHE']=MODEL_DIR
#chat = ChatTTS.Chat()
#chat.load_models(compile=True if os.getenv('compile','true').lower()!='false' else False)




text="你好啊朋友们,听说今天是个好日子,难道不是吗？"
prompt='[oral_2][laugh_0][break_0]'
#
torch.manual_seed(3333)
rand_spk = chat.sample_random_speaker()


wavs = chat.infer([text], use_decoder=True,params_infer_code={'spk_emb': rand_spk,'prompt':'[speed_1]'} ,skip_refine_text=True,params_refine_text= {'prompt': prompt})
# 初始化一个空的numpy数组用于之后的合并
combined_wavdata = np.array([], dtype=wavs[0][0].dtype)  # 确保dtype与你的wav数据类型匹配

for wavdata in wavs:
    combined_wavdata = np.concatenate((combined_wavdata, wavdata[0]))
sf.write('test.wav', combined_wavdata, 24000)

