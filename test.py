import os 
TrainPath = 'lsvc2017/lsvc_train.txt'
f = open(TrainPath)
fout = open('new_train.txt','w')
for line in f.readlines(): 
    contents = line.strip().split(',')
    for i in range(len(contents)-1):
        fout.write(contents[0] + ',' + contents[i+1] + '\n')
fout.close()
f.close()
