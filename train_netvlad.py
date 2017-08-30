import mxnet as mx
import numpy as np
import os

from easydict import EasyDict as edict

config = edict()
config.NUM_VLAD_CENTERS =10
config.NUM_LABEL =500
config.LEARNING_RATE =0.1
config.FEA_LEN = 4096


def _save_model(model_prefix, rank=0):
	import os
	if model_prefix is None:
		return None
	dst_dir = os.path.dirname(model_prefix)
	if not os.path.isdir(dst_dir):
		os.mkdir(dst_dir)
	return mx.callback.do_checkpoint(model_prefix if rank == 0 else "%s-%d" % (
		model_prefix, rank))


def tensor_vstack(tensor_list, pad=0):
    """
    vertically stack tensors
    :param tensor_list: list of tensor to be stacked vertically
    :param pad: label to pad with
    :return: tensor with max shape
    """
    ndim = len(tensor_list[0].shape)
    dtype = tensor_list[0].dtype
    islice = tensor_list[0].shape[0]
    dimensions = []
    first_dim = sum([tensor.shape[0] for tensor in tensor_list])
    dimensions.append(first_dim)
    for dim in range(1, ndim):
        dimensions.append(max([tensor.shape[dim] for tensor in tensor_list]))
    if pad == 0:
        all_tensor = np.zeros(tuple(dimensions), dtype=dtype)
    elif pad == 1:
        all_tensor = np.ones(tuple(dimensions), dtype=dtype)
    else:
        all_tensor = np.full(tuple(dimensions), pad, dtype=dtype)
    if ndim == 1:
        for ind, tensor in enumerate(tensor_list):
            all_tensor[ind*islice:(ind+1)*islice] = tensor
    elif ndim == 2:
        for ind, tensor in enumerate(tensor_list):
            all_tensor[ind*islice:(ind+1)*islice, tensor.shape[1]] = tensor
    elif ndim == 3:
        for ind, tensor in enumerate(tensor_list):
            all_tensor[ind*islice:(ind+1)*islice, :tensor.shape[1], :tensor.shape[2]] = tensor
    elif ndim == 4:
        for ind, tensor in enumerate(tensor_list):
            all_tensor[ind*islice:(ind+1)*islice, :tensor.shape[1], :tensor.shape[2], :tensor.shape[3]] = tensor
    else:
        raise Exception('Sorry, unimplemented.')
    return all_tensor


class FeaDataIter(mx.io.DataIter):
	def __init__(self, filelist, batchsize, ctx, num_classes ,data_shape, dtype = 'float32', work_load_list =None):
		self.batch_size = batchsize
		self.cur_iter = 0
#		self.max_iter = max_iter
		self.dtype = dtype
		self.ctx = ctx
		self.work_load_list = work_load_list
		self.featuredb =[]
		if not os.path.exists(filelist):
			raise Exception('Sorry, filelist {} not exsit.'.format(filelist))
		f = open(filelist)
		self.featuredb = f.readlines()
		f.close()
                self.maxshape =200
		self.total= len(self.featuredb)
		self.num_classes = num_classes
                self.cur =0

		label = np.random.randint(0, 1, [self.batch_size, ])
		data = np.random.uniform(-1, 1, [self.batch_size, data_shape[0],data_shape[1]])
		self.data = [mx.nd.array(data, dtype=self.dtype)]
		self.label =[ mx.nd.array(label, dtype=self.dtype)]
	def __iter__(self):
		return self
	@property
	def provide_data(self):
		return [mx.io.DataDesc('data', self.data[0].shape, self.dtype)]
	@property
	def provide_label(self):
                print(self.label[0].shape)
		return [mx.io.DataDesc('softmax_label', self.label[0].shape , self.dtype)]

	def iter_next(self):
		return self.cur + self.batch_size <= self.total

        def getindex(self):
            return self.cur / self.batch_size

        def getpad(self):
            if self.cur + self.batch_size > self.total:
                return self.cur + self.batch_size - self.total
            else:
                return 0

	def next(self):
		if self.iter_next():
			self.get_batch()
			self.cur += self.batch_size
#			return self.im_info, \
			return  mx.io.DataBatch(data=self.data, label=self.label,
			                       pad=self.getpad(), index=self.getindex(),
			                       provide_data=self.provide_data, provide_label=self.provide_label)
		else:
			raise StopIteration

	def __next__(self):
		return self.next()
	def reset(self):
		self.cur_iter = 0


	def get_data_label(self,iroidb):
                num_samples = len(iroidb)
		label_array = []
		data_array =[]
		for line in iroidb:
                    datapath  = line.split(',')[0]
                    datapath = '/workspace/data/trainval/' + datapath +'_fc6_vgg19_frame.binary' 
#                    label_tensor = np.zeros((1))
#                    label_tensor[:] = int(line.split(",")[1])
		    label_array.append([int(line.split(',')[1])])
                    data = np.fromfile(datapath,dtype='float32').reshape(-1,config.FEA_LEN)
                    data_tensor = np.zeros((self.maxshape,data.shape[1]))
                    if data.shape[0] > self.maxshape:
                        import random
                        radstart = random.randint(0, data.shape[0] - self.maxshape -1 )
                        data_tensor = data[radstart:radstart+self.maxshape]
                    else:
                        data_tensor[0:data.shape[0],:] = data
#                   data_tensor[0,0,:,:] = data
#                    print(data_tensor.shape)
		    data_array.append(data_tensor)

		return np.array(data_array), np.array(label_array)



	def get_batch(self):
		# slice roidb
		cur_from = self.cur
		cur_to = min(cur_from + self.batch_size, self.total)
		roidb = [self.featuredb[i] for i in range(cur_from, cur_to)]

		# decide multi device slice
		work_load_list = self.work_load_list
		ctx = self.ctx
		if work_load_list is None:
			work_load_list = [1] * len(ctx)
		assert isinstance(work_load_list, list) and len(work_load_list) == len(ctx), \
			"Invalid settings for work load. "
		slices = mx.executor_manager._split_input_slice(self.batch_size, work_load_list)

		# get testing data for multigpu
		# each element in the list is the data used by different gpu
		data_list = []
		label_list = []
		for islice in slices:
			iroidb = [self.featuredb[i] for i in range(islice.start, islice.stop)]
			data, label = self.get_data_label(iroidb)
			data_list.append(data)
			label_list.append(label)
                #print(data_list.shape())
		# pad data first and then assign anchor (read label)
                
		data_tensor = tensor_vstack(data_list)
                              
                label_tensor = np.vstack(label_list)
#		label_tensor = [batch for batch in label_list]

		self.data =[mx.nd.array([batch for batch in data_tensor])]
                print('data finish')
		self.label = [mx.nd.array([batch for batch in label_tensor])]
                print('label finish')


def netvlad(batchsize, num_centers, num_output,**kwargs):
	input_data = mx.symbol.Variable(name="data")
        
	input_centers = mx.symbol.Variable(name="centers",shape=(num_centers,config.FEA_LEN),init = mx.init.Xavier())

        w = mx.symbol.Variable('weights_vlad',
                            shape=[num_centers, config.FEA_LEN],init= mx.initializer.Xavier())
        b = mx.symbol.Variable('biases', shape=[1,num_centers],init = mx.initializer.Xavier())

       
	weights = mx.symbol.dot(name='w', lhs=input_data, rhs = w, transpose_b = True)
        weights = mx.symbol.broadcast_sub(weights,b)

	softmax_weights = mx.symbol.softmax(data=weights, axis=2,name='softmax_vald')
#	softmax_weights = mx.symbol.SoftmaxOutput(data=weights, axis=0,name='softmax_vald')

	vari_lib =[]

	for i in range(num_centers):
		y = mx.symbol.slice_axis(data=input_centers,axis=0,begin=i,end=i+1)
		temp_w = mx.symbol.slice_axis(data=softmax_weights,axis=2,begin=i,end=i+1)
		element_sub = mx.symbol.broadcast_sub(input_data, y)
		vari_lib.append(mx.symbol.batch_dot(element_sub, temp_w,transpose_a = True))

       
	for i in range(len(vari_lib)-1):
	    vari_lib[0] =mx.symbol.concat(vari_lib[0],vari_lib[i+1],dim=2)

        
	norm = mx.symbol.L2Normalization(vari_lib[0],mode='instance')
	norm = mx.symbol.Flatten(norm)
	norm = mx.symbol.L2Normalization(norm)

	weights = mx.symbol.FullyConnected(name='w', data=norm, num_hidden=num_output)
	softmax_label = mx.symbol.SoftmaxOutput(data=weights,name='softmax')

	group = mx.symbol.Group([softmax_label, mx.symbol.BlockGrad(softmax_weights)])

	return group


def _load_model(model_prefix,load_epoch,rank=0):
	import os
	assert model_prefix is not None
	sym, arg_params, aux_params = mx.model.load_checkpoint(
		model_prefix, load_epoch)
 #   logging.info('Loaded model %s_%04d.params', model_prefix, args.load_epoch)
	return (sym, arg_params, aux_params)

def _get_lr_scheduler(lr, lr_factor=None, begin_epoch = 0 ,lr_step_epochs='',epoch_size=0):
	if not lr_factor or lr_factor >= 1:
		return (lr, None)

	step_epochs = [int(l) for l in lr_step_epochs.split(',')]
	adjustlr =lr
	for s in step_epochs:
		if begin_epoch >= s:
			adjustlr *= lr_factor
	if lr != adjustlr:
		logging.info('Adjust learning rate to %e for epoch %d' % (lr, begin_epoch))

	steps = [epoch_size * (x - begin_epoch) for x in step_epochs if x - begin_epoch > 0]
	return (lr, mx.lr_scheduler.MultiFactorScheduler(step=steps, factor=lr_factor))



def train():
        print("training begin")
	kv_store = 'device'
	# kvstore
	kv = mx.kvstore.create(kv_store)

	model_prefix = 'model/netvlad'
	optimizer = 'sgd'
	wd =0.05


	load_epoch =0
        gpus = '0,1'
        top_k = 0
        batch_size =32
        disp_batches =40

        devs = mx.cpu() if gpus is None or gpus is '' else [
                mx.gpu(int(i)) for i in gpus.split(',')]

	train_data = FeaDataIter("new_train.txt",batch_size,devs,config.NUM_LABEL,(200,config.FEA_LEN))
	val_data  = FeaDataIter("new_val.txt",batch_size,devs,config.NUM_LABEL,(200,config.FEA_LEN))
        print("loading data")
	lr, lr_scheduler = _get_lr_scheduler(config.LEARNING_RATE, 0.1,0,'2,5',train_data.total)

	optimizer_params = {
		'learning_rate': lr,
		'wd': wd,
		'lr_scheduler': lr_scheduler}

	checkpoint = _save_model(model_prefix, kv.rank)

        sym_vlad = netvlad(batch_size,config.NUM_VLAD_CENTERS,config.NUM_LABEL)

	data_shape_dict = dict(train_data.provide_data + train_data.provide_label)
#	data_shape_dict = dict(train_data.provide_data)
        print(data_shape_dict)
	arg_shape, out_shape, aux_shape = sym_vlad.infer_shape(**data_shape_dict)
        print(out_shape)
	# create model
	model = mx.mod.Module(
		context=devs,
		symbol=sym_vlad 
	)

	initializer = mx.init.Xavier(
		rnd_type='gaussian', factor_type="in", magnitude=2)


	eval_metrics = ['accuracy']
	if top_k > 0:
		eval_metrics.append(mx.metric.create('top_k_accuracy', top_k=top_k))

#	if optimizer == 'sgd':
#	    optimizer_params['multi_precision'] = True

	batch_end_callbacks = [mx.callback.Speedometer(batch_size, disp_batches)]

#	monitor = mx.mon.Monitor(args.monitor, pattern=".*") if args.monitor > 0 else None
	monitor = None

#	data_shape_dict = dict(train_data.provide_data + train_data.provide_label)

#	arg_shape, out_shape, aux_shape = model.infer_shape(**data_shape_dict)
#        print(out_shape)
#	fea_len = out_shape[1]
#	center = mx.nd.array(config.NUM_VLAD_CENTERS,fea_len)

#	arg_shape_dict = dict(zip(train_data.list_arguments(), arg_shape))
#	out_shape_dict = dict(zip(train_data.list_outputs(), out_shape))
#	aux_shape_dict = dict(zip(train_data.list_auxiliary_states(), aux_shape))

#	sym,arg_params,aux_params = _load_model()


	model.fit(train_data,
			  begin_epoch=load_epoch if load_epoch else 0,
			  num_epoch=10,
			  eval_data=val_data,
			  eval_metric=eval_metrics,
			  kvstore=kv_store,
			  optimizer=optimizer,
			  optimizer_params=optimizer_params,
			  initializer=initializer,
			  arg_params=None,
			  aux_params=None,
			  batch_end_callback=batch_end_callbacks,
			  epoch_end_callback=checkpoint,
			  allow_missing=True,
			  monitor=monitor)



if __name__ == '__main__':
        print("aa")
	train()

