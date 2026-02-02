import requests
import time
import datetime
import re
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import urllib3

# 1. 环境与安全配置
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''

# --- 2. 配置区域 (改为从 GitHub Secrets 读取) ---
TOKEN = os.getenv("PUSH_TOKEN") 
MAIL_PASS = os.getenv("MAIL_PASS")
MAIL_USER = os.getenv("MAIL_USER") 
RECEIVER = os.getenv("RECEIVER")
MAIL_HOST = "smtp.qq.com"  # 添加邮件服务器配置


def get_line(limit):
    """
    【阶梯门槛逻辑】保留所有成本拆解注释
    计算公式：(申购费1.2%*0.1) + (0.2元最低佣金 / 限额) + 利润垫
    """
    if limit <= 0: return 999 
    if limit <= 10: return 2.6   # 10元档： 佣金 0.2 元占比极高（2%），溢价没到 2.6% 根本没肉。 
    if limit <= 100: return 0.8
    if limit <= 500: return 0.5
    if limit <= 1000: return 0.4
    if limit <= 5000: return 0.3
    return 0.3


def calculate_salary(limit, yijia_rate, apply_fee_str, fund_id=''):
    """【工资核算逻辑】精准独立计算每只基金收益"""
    try:
        fee_raw = float(apply_fee_str.replace('%', '')) if apply_fee_str else 1.2
        real_fee_rate = (fee_raw * 0.1) / 100 
    except:
        real_fee_rate = 0.0012
    
    commission = max(0.2, limit * 0.0001) 
    
    # --- 账户数逻辑 ---
    if fund_id == '161226' or fund_id.startswith('5'):
        account_count = 1
    else:
        account_count = 6

    single_profit = (limit * (yijia_rate / 100)) - (limit * real_fee_rate) - commission
    return round(max(0, single_profit * account_count), 2), account_count


def send_email(title, content):
    """发送邮件提醒"""
    try:
        message = MIMEText(content, 'plain', 'utf-8')
        message['From'] = MAIL_USER  
        message['To'] = RECEIVER
        message['Subject'] = Header(title, 'utf-8')
        server = smtplib.SMTP_SSL(MAIL_HOST, 465)
        server.login(MAIL_USER, MAIL_PASS)
        server.sendmail(MAIL_USER, [RECEIVER], message.as_string())
        server.quit()
        print(f"✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


def task():
    # --- 周末检测逻辑 ---
    import datetime
    if datetime.datetime.now().weekday() >= 5:
        print("今天周末，好好休息，不巡逻啦！(～￣▽￣)～")
        return 

    print(f"\n开始巡逻...")
    api_configs = [
        {'url': 'https://www.jisilu.cn/data/lof/stock_lof_list/', 'name': '股票LOF'},
        {'url': 'https://www.jisilu.cn/data/lof/index_lof_list/', 'name': '指数LOF'},
        {'url': 'https://www.jisilu.cn/data/qdii/qdii_list/', 'name': 'QDII-欧'},
        {'url': 'https://www.jisilu.cn/data/qdii/qdii_list/A', 'name': 'QDII-亚'},
        {'url': 'https://www.jisilu.cn/data/qdii/qdii_list/C', 'name': 'QDII-商品'}
    ]
    
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.jisilu.cn/'}
    found_list = []
    seen_ids = set()
    total_day_salary = 0.0 
    total_capital = 0.0
    
    for config in api_configs:
        try:
            r = requests.get(config['url'], headers=headers, timeout=15, verify=False)
            if r.status_code != 200: 
                continue
            rows = r.json().get('rows', [])
            for row in rows:
                item = row['cell']
                fund_nm = item.get('fund_nm', '')
                fund_id = item.get('fund_id', '')

                # 去重判断
                if fund_id in seen_ids:
                    continue

                if "ETF" in fund_nm.upper() and "LOF" not in fund_nm.upper(): 
                    continue
                
                status = item.get('apply_status', '')
                limit_val = None
                if "限" in status:
                    nums = re.findall(r'\d+', status)
                    if nums:
                        limit_val = int(nums[0])
                        if "千" in status: 
                            limit_val *= 1000
                
                if limit_val is None or limit_val > 6000 or "万" in status or limit_val < 10:
                    continue
                
                raw_discount = item.get('discount_rt', None)
                if raw_discount is None: 
                    continue
                yijia_rate = float(str(raw_discount).replace('%', ''))
                
                threshold = get_line(limit_val)
                if yijia_rate > threshold:
                    apply_fee = item.get('apply_fee', '1.20%')
                    est_salary, accounts = calculate_salary(limit_val, yijia_rate, apply_fee, fund_id)
                    
                    # 【新增】最低收益过滤：预计收益必须>2元才提醒
                    if est_salary > 2:
                        seen_ids.add(fund_id)
                        total_day_salary += est_salary
                        total_capital += (limit_val * accounts)
                        found_list.append({
                            'fund_nm': fund_nm, 
                            'fund_id': fund_id, 
                            'yijia_rate': yijia_rate,
                            'limit_val': limit_val, 
                            'accounts': accounts, 
                            'est_salary': est_salary, 
                            'apply_fee': apply_fee
                        })
        except: 
            continue

    if found_list:
        found_list.sort(key=lambda x: x['est_salary'], reverse=True)
        now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        
        display_title = f"✨ 发现可套利基金！今日小钱钱预计：+{total_day_salary:.2f}元 ✨"
        
        content_lines = [
            "(๑•̀ㅂ•́)و✧ 报告主人！今日份的小钱钱已送达！",
            f"巡逻时间：{now_time}",
            f"预计小钱钱：+{total_day_salary:.2f} 元",
            f"占用资金：{total_capital:.0f} 元",
            "================================"
        ]
        
        for idx, f in enumerate(found_list, 1):
            if f['fund_id'] == '161226':
                memo = " (⚠️唯一身份证标的)"
            elif f['fund_id'].startswith('5'):
                memo = " (⚠️沪市基金/单户标的)"
            else:
                memo = ""
            
            acc_label = f"{f['accounts']}户{memo}"
            
            item_block = [
                f"\n【{idx}】{f['fund_nm']} ({f['fund_id']})",
                f"[溢价率] : {f['yijia_rate']}%",
                f"[申购费] : {f['apply_fee']}",
                f"[限额额] : {f['limit_val']} 元",
                f"[账户数] : {acc_label}",
                f"[预计收益] : +{f['est_salary']} 元",
                f"--------------------------------"
            ]
            content_lines.extend(item_block)
        
        content = "\n".join(content_lines)
        print(content)
        
        # 微信推送
        try:
            requests.post("http://www.pushplus.plus/send", 
                          data={'token': TOKEN, 'title': display_title, 'content': content}, 
                          timeout=10)
        except: 
            pass
        
        # 邮件推送
        send_email(display_title, content)
    else:
        print("📭 暂未发现达标机会。")


if __name__ == "__main__":
    task()
