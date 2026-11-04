import subprocess
import re

def get_lm_sensors(flag=True):
    val=float('NaN')
    if not flag:
        return val
    # apt-get install lm-sensors
    ret=subprocess.run('sensors', shell=True, stdout=subprocess.PIPE)
    D=ret.stdout.decode()
    for l in D.split('\n'):
        if re.match('Composite',l):
            # print(l.split()[1])
            # print(re.findall(r'\d+', l.split()[1]))
            # print(re.sub(r'\D','', l.split()[1]))
            val=re.sub(r'[^\d.]','', l.split()[1])
    return float(val)

def get_uptime(flag=True):
    val=float('NaN')
    if not flag:
        return val
    # apt-get install lm-sensors
    ret=subprocess.run('uptime', shell=True, stdout=subprocess.PIPE)
    D=ret.stdout.decode()
    d=D.split('load average')[1]
    # print(d)
    val=re.sub(r'[^\d.]','', d.split(',')[0])
    return float(val)

def get_iwconfig(flag=True):
    val=float('NaN')
    if not flag:
        return val
    # apt-get install lm-sensors
    ret=subprocess.run('iwconfig', shell=True, stdout=subprocess.PIPE)
    D=ret.stdout.decode()
    for l in D.split('\n'):
        if 'Signal level=' in l:
            val=re.sub(r'[^\d.]','', l.split('Signal level')[1])
    return float(val)

def get_memory_usage(flag=True):
    val=float('NaN')
    if not flag:
        return val
    # apt-get install lm-sensors
    ret=subprocess.run('free', shell=True, stdout=subprocess.PIPE)
    D=ret.stdout.decode()
    for l in D.split('\n'):
        if 'Mem:' in l:
            d=l.split()
            val=float(d[2])/float(d[1])
    return float(val)

def get_cpu_clock(flag=True):
    val=float('NaN')
    if not flag:
        return val
    # apt-get install lm-sensors
    ret=subprocess.run('cat /proc/cpuinfo', shell=True, stdout=subprocess.PIPE)
    D=ret.stdout.decode()
    #print(D)
    V=[]
    for l in D.split('\n'):
        if 'cpu MHz' in l:
            val=re.sub(r'[^\d.]','', l)
            V.append(float(val))
    return V

if __name__ == '__main__':
    print(get_lm_sensors())
    print(get_uptime())
    print(get_iwconfig(False))
    print(get_memory_usage())
    print(get_cpu_clock())
