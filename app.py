import os
import re
import sys
from pathlib import Path
import torch
import torch._dynamo
torch._dynamo.config.suppress_errors = True
torch._dynamo.config.cache_size_limit = 64
torch._dynamo.config.suppress_errors = True
torch.set_float32_matmul_precision('high')
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
VERSION='0.8'

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
from flask import Flask, request, render_template, jsonify,  send_from_directory
import logging
from logging.handlers import RotatingFileHandler
from waitress import serve
load_dotenv()
import hashlib,webbrowser
from modelscope import snapshot_download
import numpy as np
import time
import LangSegment
LangSegment.setfilters(["zh","en","ja"])

# 读取 .env 变量
WEB_ADDRESS = os.getenv('WEB_ADDRESS', '127.0.0.1:9966')

# 默认从 modelscope 下载模型,如果想从huggingface下载模型，请将以下3行注释掉
CHATTTS_DIR = snapshot_download('pzc163/chatTTS',cache_dir=MODEL_DIR)
chat = ChatTTS.Chat()
# 通过将 .env中 compile设为false，禁用推理优化. 其他为启用。一定情况下通过禁用，能提高GPU效率
chat.load_models(source="local",local_path=CHATTTS_DIR, compile=True if os.getenv('compile','true').lower()!='false' else False)

# 如果希望从 huggingface.co下载模型，将以下注释删掉。将上方3行内容注释掉
#os.environ['HF_HUB_CACHE']=MODEL_DIR
#os.environ['HF_ASSETS_CACHE']=MODEL_DIR
#chat = ChatTTS.Chat()
#chat.load_models(compile=True if os.getenv('compile','true').lower()!='false' else False)




# 配置日志
# 禁用 Werkzeug 默认的日志处理器
log = logging.getLogger('werkzeug')
log.handlers[:] = []
log.setLevel(logging.WARNING)

app = Flask(__name__, 
    static_folder=ROOT_DIR+'/static', 
    static_url_path='/static',
    template_folder=ROOT_DIR+'/templates')

root_log = logging.getLogger()  # Flask的根日志记录器
root_log.handlers = []
root_log.setLevel(logging.WARNING)
app.logger.setLevel(logging.WARNING) 
# 创建 RotatingFileHandler 对象，设置写入的文件路径和大小限制
file_handler = RotatingFileHandler(LOGS_DIR+f'/{datetime.datetime.now().strftime("%Y%m%d")}.log', maxBytes=1024 * 1024, backupCount=5)
# 创建日志的格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# 设置文件处理器的级别和格式
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)
# 将文件处理器添加到日志记录器中
app.logger.addHandler(file_handler)
app.jinja_env.globals.update(enumerate=enumerate)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(app.config['STATIC_FOLDER'], filename)


@app.route('/')
def index():
    return render_template("index.html",weburl=WEB_ADDRESS,version=VERSION)

# 将数字转为文字
def num2text(t,lang="zh"):
    if lang=='zh':
        return t.replace('1','一').replace('2','二').replace('3','三').replace('4','四').replace('5','五').replace('6','六').replace('7','七').replace('8','八').replace('9','九').replace('0','零')
    return t.replace('1',' one ').replace('2',' two ').replace('3',' three ').replace('4',' four ').replace('5',' five ').replace('6',' six ').replace('7','seven').replace('8',' eight ').replace('9',' nine ').replace('0',' zero ')


# 切分中英
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

# 根据文本返回tts结果，返回 filename=文件名 url=可下载地址
# 请求端根据需要自行选择使用哪个
# params:
#
# text:待合成文字
# voice：音色
# custom_voice：自定义音色值
# skip_refine: 1=跳过refine_text阶段，0=不跳过
# temperature
# top_p
# top_k
# prompt：
@app.route('/tts', methods=['GET', 'POST'])
def tts():
    # 原始字符串
    text = request.args.get("text","").strip() or request.form.get("text","").strip()
    prompt = request.form.get("prompt",'')
    try:
        custom_voice=int(request.form.get("custom_voice",0))
        voice =  custom_voice if custom_voice>0  else int(request.form.get("voice",2222))
    except Exception:
        voice=2222
    print(f'{voice=},{custom_voice=}')
    temperature = float(request.form.get("temperature",0.3))
    top_p = float(request.form.get("top_p",0.7))
    top_k = int(request.form.get("top_k",20))
    
    try:
        skip_refine = int(request.form.get("skip_refine",0))
        is_split = int(request.form.get("is_split",0))
    except Exception:
        skip_refine=is_split=0
    
    app.logger.info(f"[tts]{text=}\n{voice=},{skip_refine=}\n")
    if not text:
        return jsonify({"code": 1, "msg": "text params lost"})
    std, mean = torch.load(f'{CHATTTS_DIR}/asset/spk_stat.pt').chunk(2)
    torch.manual_seed(voice)

    rand_spk = chat.sample_random_speaker()
    #rand_spk = torch.randn(768) * std + mean

    audio_files = []
    md5_hash = hashlib.md5()
    md5_hash.update(f"{text}-{voice}-{skip_refine}-{prompt}".encode('utf-8'))
    datename=datetime.datetime.now().strftime('%Y%m%d-%H_%M_%S')
    filename = datename+'-'+md5_hash.hexdigest()[:8] + ".wav"

    start_time = time.time()
    
    # 中英按语言分行
    text_list=[t.strip() for t in text.split("\n") if t.strip()]
    new_text=text_list if is_split==0 else split_text(text_list)
    print(f'{new_text=}')
    wavs = chat.infer(new_text, use_decoder=True, skip_refine_text=True if int(skip_refine)==1 else False,params_infer_code={
        'spk_emb': rand_spk,
        'temperature':temperature,
        'top_P':top_p,
        'top_K':top_k
    }, params_refine_text= {'prompt': prompt},do_text_normalization=False)

    end_time = time.time()
    inference_time = end_time - start_time
    inference_time_rounded = round(inference_time, 2)
    print(f"推理时长: {inference_time_rounded} 秒")

    # 初始化一个空的numpy数组用于之后的合并
    combined_wavdata = np.array([], dtype=wavs[0][0].dtype)  # 确保dtype与你的wav数据类型匹配

    for wavdata in wavs:
        combined_wavdata = np.concatenate((combined_wavdata, wavdata[0]))

    sample_rate = 24000  # Assuming 24kHz sample rate
    audio_duration = len(combined_wavdata) / sample_rate
    audio_duration_rounded = round(audio_duration, 2)
    print(f"音频时长: {audio_duration_rounded} 秒")

    sf.write(WAVS_DIR+'/'+filename, combined_wavdata, 24000)

    audio_files.append({
        "filename": WAVS_DIR + '/' + filename,
        "url": f"http://{request.host}/static/wavs/{filename}",
        "inference_time": inference_time_rounded,
        "audio_duration": audio_duration_rounded
    })
    result_dict={"code": 0, "msg": "ok", "audio_files": audio_files}
    # 兼容pyVideoTrans接口调用
    if len(audio_files)==1:
        result_dict["filename"]=audio_files[0]['filename']
        result_dict["url"]=audio_files[0]['url']

    return jsonify(result_dict)

def ClearWav(directory):
    # 获取../static/wavs目录中的所有文件和目录
    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

    if not files:
        return False, "wavs目录内无wav文件"

    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
                print(f"已删除文件: {file_path}")
            elif os.path.isdir(file_path):
                print(f"跳过文件夹: {file_path}")
        except Exception as e:
            print(f"文件删除错误 {file_path}, 报错信息: {e}")
            return False, str(e)
    return True, "所有wav文件已被删除."


@app.route('/clear_wavs', methods=['POST'])
def clear_wavs():
    dir_path = 'static/wavs'  # wav音频文件存储目录
    success, message = ClearWav(dir_path)
    if success:
        return jsonify({"code": 0, "msg": message})
    else:
        return jsonify({"code": 1, "msg": message})

try:
    host = WEB_ADDRESS.split(':')
    print(f'启动:{host}')
    webbrowser.open(f'http://{WEB_ADDRESS}')
    serve(app,host=host[0], port=int(host[1]))
except Exception:
    pass

