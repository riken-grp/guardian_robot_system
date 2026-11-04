from pymongo import DESCENDING, MongoClient

class manipulate_scenario():
    def __init__(self, host, port, db_name, col_name):
        self.client = MongoClient(host, port)
        self.db=self.client[db_name]
        self.col=self.db[col_name]
    def find(self, name):
        query={'name':name}
        return self.col.find_one(query)
    def count(self,query={}):
        return self.col.count_documents(query)
    def activate(self,name,flag=True):
        c=self.find(name)
        q={"_id":c["_id"]}
        if flag:
            self.col.update_one(q, {'$set':{'status':'active'}})
        else:
            self.col.update_one(q, {'$set':{'status':'inactive'}})
        return self.find(name)
    def deactivate(self,name):
        return self.activate(name, False)
    def set_priority(self,name,p=0):
        c=self.find(name)
        q={"_id":c["_id"]}
        self.col.update_one(q, {'$set':{'priority':p}})
        return self.find(name)
    def get_scenario_list(self):
        D=self.col.find({},{"name":1})
        return [doc["name"] for doc in D]
    def get_active_list(self):
        D=self.col.find({},{"name":1,"status":1})
        N=[]
        for doc in D:
            if doc['status']=='active':
                N.append(doc["name"])
        return N
    def get_inactive_list(self):
        D=self.col.find({},{"name":1,"status":1})
        N=[]
        for doc in D:
            if doc['status']=='inactive':
                N.append(doc["name"])
        return N
    def deactivate_except_for(self, names):
        N=[]
        if isinstance(names, str):
            N.append(names)
        else:
            N=names
        L=self.get_scenario_list()
        cc=len(set(N) & set(L))
        if cc==0:
            return 0
        for l in L:
            if l in N:
                self.activate(l)
            else:
                self.deactivate(l)
        return cc
    def activate_except_for(self, names):
        N=[]
        if isinstance(names, str):
            N.append(names)
        else:
            N=names
        L=self.get_scenario_list()
        cc=len(set(L) - set(N))
        if cc==0:
            return 0
        for l in L:
            if l in N:
                self.deactivate(l)
            else:
                self.activate(l)
        return cc
