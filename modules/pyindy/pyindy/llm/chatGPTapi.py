#!/usr/bin/python3
import requests
from openai import OpenAI
from pymongo import DESCENDING, MongoClient
from bson import ObjectId
import copy

class prompt_from_mongodb():
    def __init__(self, host, port, dbname='dictionary'):
        client = MongoClient(host, port)
        db=client[dbname]
        self.col=db['llm_prompts']
    def get_list(self):
        D=self.col.find()
        L=[]
        for d in D:
            L.append(str(d['_id']))
        return L
    def insert(self, type, prompt):
        id=self.col.insert_one({'type': type, 'prompt': prompt})
        return id
    def get(self, id):
        _id=ObjectId(id)
        d=self.col.find_one({'_id':_id})
        # print(d['prompt'])
        return d['prompt']

class gpt_agent():
    def __init__(self, name='indy', url="http://localhost:8889"):
        key=self.get_open_ai_key(url)
        if key is not False:
            self.chatter = OpenAI(api_key=key)
            self.model="gpt-4o"
            # self.model="gpt-4-turbo"
            # model="gpt-3.5-turbo"
        else:
            print("Can not create the agent")
        self.name=name
        self.retry=0
    def get_open_ai_key(self, url):
        try:
            res=requests.get(url)
            if res.status_code == 200:
                return res.text
            else:
                print("start the key server")
                return False
        except requests.exceptions.RequestException as e:
            print("Error: ", e)
            print("start the key server")
            return False
    def reply(self, prompt):
        msgs=[{"role":"system","content":prompt}]
        res=self.chatter.chat.completions.create(model=self.model, messages=msgs, temperature=1)
        print(res.choices[0].message.content)
        return res
    def generate_utterance(self, history, role, cond):
        # print("########################################################")
        instruction=f'対話履歴にマッチした {self.name} の発言を生成してください。\n\n'
        condt=copy.copy(cond)
        if self.retry > 0:
            self.retry=self.retry-1
            condt.append('+もし相手が発話の途中だと推測される場合は False を出力してください.\n')        
        pre_history = '対話履歴は以下のようになっています。\n'
        text=role + instruction + str(condt) + pre_history  + history
        # print(text)
        print(condt)
        res=self.reply(text)
        print(f'##### {res.choices[0].message.content} #######')
        return res.choices[0].message.content
    def judge_yes_no(self, history, prompt=''):
        return True
