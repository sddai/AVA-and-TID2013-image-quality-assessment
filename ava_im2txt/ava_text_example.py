# MobileNetV2 trained on AVA dataset for NIMA challenge.

# This is modified vanilla network made to converge faster to good distribution of means.
# added layer, added regularization to the loss.


# training: pretrain for one epoch,
# train: 20 epochs

# val loss and accuracy will NOT imporove, model overfits, but histogram becomes better.


import os
import math
import random
import warnings


import tensorflow as tf
import keras
import numpy as np
import pandas as pd
import pickle
import json

from keras.preprocessing.image import load_img
from keras.preprocessing.image import img_to_array
from keras.applications.imagenet_utils import decode_predictions

from keras.models import Model
from keras.layers import Dense, Dropout, Flatten, LSTM, Embedding, concatenate, BatchNormalization, Bidirectional, Input
from keras import backend as K
from keras.callbacks import ReduceLROnPlateau, ModelCheckpoint, LearningRateScheduler
from keras.utils import Sequence # out custom data generator

import gensim


# silence PIL warnings
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
warnings.filterwarnings("ignore", "(Possibly )?corrupt EXIF data", UserWarning)

'''
# attempt to limit gpu ram
from tensorflow.keras.backend import set_session
config = tf.ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = 0.5
set_session(tf.Session(config=config))
'''


# Suppress tensorflow garbage
os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


# training parameters
pretrain_epochs = 1
epochs = 25
batch_size = 16
val_split = 0.1
image_noise = 0.003 # otional, uncomment in generator




# Load word2vec


print('Indexing word vectors')

# 4 GB RAM
w2v_model = gensim.models.KeyedVectors.load_word2vec_format('GoogleNews-vectors-negative300.bin', binary=True)



WORD2VEC_EMBEDDING_DIM = 300
vocab_size = len(w2v_model.wv.vocab)

# ANOTHER 4 GM RAM
embedding_matrix = np.zeros((vocab_size+1, WORD2VEC_EMBEDDING_DIM))

fast_vocab = {}

# just to emphasize nullvect
embedding_matrix[0] = np.zeros(WORD2VEC_EMBEDDING_DIM)

for idx, item in enumerate(w2v_model.wv.vocab):
    try:
        fast_vocab[item] = idx
        embedding_matrix[idx+1, :] = w2v_model[item]
    except KeyError:
        pass # zero vec for unknown words

fast_vocab[" "] = 0 # nullvect

print('Done indexing word vectors')


print('Processing dataset')
# read im2text ava dataset
with open('ava_im2txt.json', 'r') as f:
    txt_dataset = json.load(f)

fast_txt_index = {}

maxlen = 0
for item in txt_dataset:
    file_index, sentences = item
    # make 3 sentences for each index
    while len(sentences) <3:
        sentences.append(sentences[-1])
    
    for sentence in sentences:
        maxlen = max([len(sentence[0]), maxlen])
    
    fast_txt_index[file_index] = sentences
    # each sentence is a list of words and score

MAX_SEQUENCE_LENGTH = maxlen

print('Max sequence length: {}'.format(maxlen))

print('Finished processing dataset')

del(w2v_model)
'''
with open("datasets.pickle", "wb") as f:
    pickle.dump([vocab_size, fast_vocab, fast_txt_index, MAX_SEQUENCE_LENGTH, embedding_matrix], f, protocol=pickle.HIGHEST_PROTOCOL)
'''

def tokenizer(sent_list, maxlen=MAX_SEQUENCE_LENGTH):
    sent_tokenized = []
    for word in sent_list:
        word_l = word.lower().strip()
        # unknown word to nullvect
        sent_tokenized.append(fast_vocab.get(word_l, 0))
    # zero pad sequence
    if len(sent_tokenized) < maxlen:
        sent_tokenized += [0]*(maxlen-len(sent_tokenized))
    return np.array(sent_tokenized)
        




data_path = '../datasets/AVA_dataset/images/images' # some images do not exist or do not open, I didn't clean dataset
labels_path = '../datasets/AVA_dataset/AVA.txt'


# load model train and validation data

with open('ava_labels_test.json', 'r') as f:
    data = json.load(f)
    
label_test = []
for value in data:
    label_test.append([value["image_id"]]+value["label"])
    
label_test = np.array(label_test, dtype=float)

histograms = label_test[:,1:]
histograms /=  histograms.sum(axis=1)[:,np.newaxis]

# First column is id, other 10 - histogram
label_test[:,1:] = histograms




with open('ava_labels_train.json', 'r') as f:
    data = json.load(f)
    
label_train = []
for value in data:
    label_train.append([value["image_id"]]+value["label"])
    
label_train = np.array(label_train, dtype=float)

histograms = label_train[:,1:]
histograms /=  histograms.sum(axis=1)[:,np.newaxis]

# First column is id, other 10 - histogram
label_train[:,1:] = histograms



print(label_train.shape)
print(label_test.shape)





'''
# prepare histograms ---------------
label_data = pd.read_csv(labels_path, header=None, sep=' ')
broken_ones = label_data.isnull().values.any()
print('Any nans in dataset: {}'.format(broken_ones))
# in original dataset
# col 2 - img id
# col 3-12 - histogram
label_np = label_data.values[:,1:12].astype(np.float32)


# normalize histograms
histograms = label_np[:,1:]
histograms /=  histograms.sum(axis=1)[:,np.newaxis]

# First column is id, other 10 - histogram
label_np[:,1:] = histograms

print('Got labels: {}'.format(len(label_np)))




print(label_np.shape)



# create train-test set
np.random.shuffle(label_np) # shuffles the array along the first axis 
n_val = int(val_split*len(label_np))
label_train = label_np[n_val:]
'''

'''
# optional: upsample tails (makes better scores for > 7), seems to overfit more:


# store elements of distribution to compute means, etc
dist_values = np.array([1,2,3,4,5,6,7,8,9,10], dtype=np.float32)
dist_values = np.expand_dims(dist_values, -1)

label_train_hist = label_train[:,1:11]
mean_scores = label_train_hist.dot(dist_values)
chosen1 = [idx for idx, x in enumerate(mean_scores) if x<4] # ~8000
chosen2 = [idx for idx, x in enumerate(mean_scores) if x>7] # ~3500

# upsample tails according to the number of elements in them
elems_to_replicate = label_train[chosen1,:]
elems_to_add = np.tile(elems_to_replicate, (8,1))  # 8*8k => +64k
label_train = np.vstack([label_train, elems_to_add])

elems_to_replicate = label_train[chosen2,:]
elems_to_add = np.tile(elems_to_replicate, (19,1)) # 19*3k = + 66k

label_train = np.vstack([label_train, elems_to_add])

print(label_train.shape)
'''



#label_test = label_np[:n_val]


# save split for further training

with open('train_test_split_cs.pickle', 'wb') as handle:
    pickle.dump({'label_train':label_train, 'label_test':label_test}, handle, protocol=pickle.HIGHEST_PROTOCOL)

# if you want to continue training, just comment out all the dataset loading above and load data:
'''
with open('train_test_split_cs.pickle', 'rb') as handle:
    dat = pickle.load(handle)

label_train = dat['label_train']
label_test = dat['label_test']
label_np = dat['all']
'''

# ----------------------------------



################################################################## Data generator

# Native model's preprocessor. It just normalizes to -1,1.
#preprocessor = keras.applications.mobilenetv2.preprocess_input

# Normalize according to ImageNet
IMAGE_NET_MEAN = [0.485, 0.456, 0.406]
IMAGE_NET_STD = [0.229, 0.224, 0.225]
# for each channel do input[channel] = (input[channel] - mean[channel]) / std[channel
def normalize_img(img):    
    img /= 255.    
    for channel in range(3):
        mean = IMAGE_NET_MEAN[channel]
        std = IMAGE_NET_STD[channel]
        img[:,:, channel] = (img[:,:, channel] - mean)/std
        
    return img

# random crops
def crop_rnd(img, height=224, width=224):
    
    h = img.shape[0]-height
    w = img.shape[1]-width
    y0 = random.randint(0,h)
    x0 = random.randint(0,w)
    
    return img[y0:y0+height , x0:x0+width, :]

# Image load and augmentation
def load_image(im, mode='train'):
    
    if mode=='train':
        original = load_img(im, target_size=(256, 256))
        numpy_image = img_to_array(original)
        # NIMA article:
        # random crop to 224,224
        numpy_image = crop_rnd(numpy_image)
        # random flip
        if np.random.randint(2)==1:
            numpy_image = np.fliplr(numpy_image)
    else:
        original = load_img(im, target_size=(224,224))
        numpy_image = img_to_array(original)
    
    # normalize to ImageNet
    numpy_image = normalize_img(numpy_image)
    # Make batch element
    # (1, 224, 224, 3)
    image_batch = np.expand_dims(numpy_image, axis=0)
    
    processed_image = image_batch
    # preprocess using vanilla normalizer
    #processed_image = preprocessor(image_batch.copy())
    
    # image is -1,1 now
    # Optional: +0.3% noise
    #if mode=='train':
    #    noise = image_noise*np.random.randn(*(processed_image.shape))
    #    processed_image = processed_image+noise
        
    return processed_image

class DataSequence(Sequence):
    """
    Keras Sequence object to train a model on larger-than-memory data.
    """
    def __init__(self, label_np, data_path, batch_size, mode='train'):
        self.df = label_np
        self.bsz = batch_size
        self.mode = mode
        # Take labels and a list of image locations in memory
        self.labels = self.df[:,1:]
        #self.im_list = [os.path.join(data_path, str(int(x)) + '.jpg') for x in self.df[:,0].tolist()]
        self.im_list = self.df[:,0]
        self.indexes = np.arange(self.df.shape[0])
        np.random.shuffle(self.indexes)
    def __len__(self):
        return int(math.ceil(len(self.df) / float(self.bsz)))
    def on_epoch_end(self):
        # Shuffles indexes after each epoch if in training mode
        # self.indexes = range(len(self.im_list))
        # shuffle only here, at the end of epoch
        if self.mode == 'train':
            np.random.shuffle(self.indexes)
    def get_batch_labels(self, inds):
        # Fetch a batch of labels        
        batch_labels = self.labels[inds]#[idx * self.bsz: (idx + 1) * self.bsz]        
        return batch_labels
    def get_batch_features(self, inds):
        # Fetch a batch of inputs        
        #print(inds)
        images = [self.im_list[i] for i in inds]
        
        
        input1 = []
        input2 = []
        input3 = []
        input4 = []
        input5 = []
        input6 = []
        input7 = []
        
        
        # get sentences
        # if intem is not found in dictionary, will throw error and go to another batch
        for idx, im_id in enumerate(images):
            
            image_loaded = load_image(os.path.join(data_path, str(int(im_id)) + '.jpg'), self.mode) 
            sentences = fast_txt_index[im_id]
            sent1, score1 = sentences[0]
            sent2, score2 = sentences[1]
            sent3, score3 = sentences[2]
            
            sent1 = tokenizer(sent1)
            sent2 = tokenizer(sent2)
            sent3 = tokenizer(sent3)
            
            # base_model.input, sequence_1_input, score_1_input, sequence_2_input, score_2_input, sequence_3_input, score_3_input
            #res[idx] = {'base_model.input':image_loaded, 'sequence_1_input':sent1, 'score_1_input':np.array(score1), 'sequence_2_input':sent2, 'score_2_input':np.array(score2), 'sequence_3_input':sent3, 'score_3_input':np.array(score3)}
            
            input1.append(image_loaded)
            input2.append(sent1)
            input3.append(score1)
            input4.append(sent2)
            input5.append(score2)
            input6.append(sent3)
            input7.append(score3)
            
            
        #return np.vstack([load_image(im, self.mode) for im in images])
        
        outs = [np.vstack(input1), input2, input3, input4, input5, input6, input7]
        return [np.array(x) for x in outs]
        
    def __getitem__(self, idx):
        #batch_x = self.get_batch_features(idx)
        #batch_y = self.get_batch_labels(idx)
        # fail-safe: if we get error during processing batch, we just switch to the next one. 
        # It works without fail, idx does not become too big
        while True:
            try:
                inds = self.indexes[(idx * self.bsz):((idx + 1) * self.bsz)].tolist()
                batch_x = self.get_batch_features(inds)
                batch_y = self.get_batch_labels(inds)
                return batch_x, batch_y
            except Exception as e:                
                #print(e)
                #print(inds)
                idx +=1
        
        #return batch_x, batch_y
############################################################ END (Data generator)





# this model only supports the data format 'channels_last' (height, width, channels).
# The default input size for this model is 224x224x3

# include_Top = False cuts too much layers on this version of keras. I will select previous layer manually.
base_model = keras.applications.mobilenetv2.MobileNetV2((224,224,3), pooling='avg', weights='imagenet', include_top=True)


# test inference ----------------------
'''
def test_inference(filename, model=base_model):
    # load an image in PIL format
    original = load_img(filename, target_size=(224, 224))
    numpy_image = img_to_array(original)
    
    numpy_image = normalize_img(numpy_image.copy())

    # (1, 224, 224, 3)
    image_batch = np.expand_dims(numpy_image, axis=0)
    
    # get the predicted probabilities for each class
    predictions = model.predict(image_batch)

    return predictions
'''
#print(test_inference(filename))
# -------------------------------------


# distribution elements to Keras
distribution_elements_row = tf.constant(np.array([1,2,3,4,5,6,7,8,9,10]), dtype='float32', name='marks')
distribution_elements = K.expand_dims(distribution_elements_row, -1)
distribution_elements_square = K.square(distribution_elements)
distribution_elements_cube = K.pow(distribution_elements, 3)


# compute squared difference of first moments
def first_moment(y_true, y_pred):
    
    means_true = K.dot(y_true, distribution_elements)
    means_pred = K.dot(y_pred, distribution_elements)
    
    return K.sqrt(K.mean(K.square(means_true-means_pred)))

# compute squared difference of second moments
def second_moment(y_true, y_pred):

    means_true = K.dot(y_true, distribution_elements)
    means_pred = K.dot(y_pred, distribution_elements)
    
    
    second_true = K.dot(y_true, distribution_elements_square)
    second_pred = K.dot(y_pred, distribution_elements_square)
    
    #E(x^2) - (E(x)^2)
    second_true = second_true - K.square(means_true)
    second_pred = second_pred - K.square(means_pred)
    
    
    return K.sqrt(K.mean(K.square(second_true-second_pred)))

def third_moment(y_true, y_pred):

    means_true = K.dot(y_true, distribution_elements)
    means_pred = K.dot(y_pred, distribution_elements)
    
    
    second_true = K.dot(y_true, distribution_elements_square)
    second_pred = K.dot(y_pred, distribution_elements_square)
    
    third_true = K.dot(y_true, distribution_elements_cube)
    third_pred = K.dot(y_pred, distribution_elements_cube)
    
    #E(x^3) - 3*E(x)*(E(x)^2) + 2*E(x)^3
    third_true = third_true - 3*means_true*second_true + 2*K.pow(means_true, 3)
    third_pred = third_pred - 3*means_true*second_pred + 2*K.pow(means_pred, 3)

    return K.sqrt(K.mean(K.square(third_true-third_pred)))



# NIMA code https://github.com/titu1994/neural-image-assessment/blob/master/train_mobilenet.py
def earth_mover_loss(y_true, y_pred):
    cdf_true = K.cumsum(y_true, axis=-1)
    cdf_pred = K.cumsum(y_pred, axis=-1)
    emd = K.sqrt(K.mean(K.square(cdf_true - cdf_pred), axis=-1))
    return K.mean(emd)

def earth_mover_loss_L1(y_true, y_pred):
    cdf_true = K.cumsum(y_true, axis=-1)
    cdf_pred = K.cumsum(y_pred, axis=-1)
    emd = K.mean(K.abs(cdf_true - cdf_pred), axis=-1)
    return K.mean(emd)
    

def my_loss(y_true, y_pred):
    # Moments part is approximately 1.2 for fitted model (bin_acc>0.75)
    # Mean emd on batch is around 0.05 - 0.07 in vanilla emd loss
    # So this loss is 3.5 - 4.8 where contribution of emd is ~3.5 and moments ~1.0
    # Reqularizing makes mean fit faster, You need ~15 epochs instead of 40-50
    
    return 50*earth_mover_loss(y_true, y_pred) + 2*first_moment(y_true, y_pred) + second_moment(y_true, y_pred)


def my_loss_L1(y_true, y_pred):
    # Moments part is approximately 1.2 for fitted model (bin_acc>0.75)
    # Mean emd on batch is around 0.05 - 0.07 in vanilla emd loss
    # So this loss is 3.5 - 4.8 where contribution of emd is ~3.5 and moments ~1.0
    # Reqularizing makes mean fit faster, You need ~15 epochs instead of 40-50
    
    return 50*earth_mover_loss_L1(y_true, y_pred) + 2*first_moment(y_true, y_pred) + second_moment(y_true, y_pred)


# chi-squared loss function, with distant parts of histgram weighted more
def chi_squared_loss(y_true, y_pred):    
    # one elem of batch
    def chi_sqr(z_true,z_pred):
        numerator = K.square(z_true - z_pred)
        denominator = tf.map_fn(lambda x: tf.where(tf.less(x, 1e-7), 1., x), z_true,  dtype='float32')        
        true_mean = tf.tensordot(z_true, distribution_elements_row, 1)
        hist_weights = 0.01 + K.square(distribution_elements_row - true_mean)        
        return tf.tensordot(tf.div(numerator,denominator), hist_weights, 1)
    # vectors are unpacked across first dimension
    batch_res = tf.map_fn(lambda x: chi_sqr(x[0],x[1]), (y_true,y_pred), dtype='float32')    
    # moments part is around 1
    return 4*K.mean(batch_res) + K.sqrt(first_moment(y_true, y_pred)) + K.sqrt(second_moment(y_true, y_pred) )


def pearson_corr_scores(y_true, y_pred):
    means_true = K.dot(y_true, distribution_elements)
    means_pred = K.dot(y_pred, distribution_elements)
    
    means_true = means_true - K.mean(means_true)
    means_pred = means_pred - K.mean(means_pred)
    
    # normalizing stage - setting a 1 variance
    means_true = K.l2_normalize(means_true, axis = 0)
    means_pred = K.l2_normalize(means_pred, axis = 0)
    
    # final result
    pearson_correlation = K.sum(means_true * means_pred)
    
    return pearson_correlation


'''
predicted mean scores are compared to 5 as cut-off score. Images with predicted scores
above  the  cut-off  score  are  categorized  as  high  quality.
'''

def bin_acc(y_true, y_pred):
    num_true = K.dot(y_true, distribution_elements)/5.0
    num_pred = K.dot(y_pred, distribution_elements)/5.0
    return K.mean(K.equal(tf.floor(num_true), tf.floor(num_pred)), axis=-1)

# mean absolute percentage error
def acc(y_true, y_pred):
    
    mean_true = K.dot(y_true, distribution_elements)
    mean_pred = K.dot(y_pred, distribution_elements)
    
    return K.mean(1.0 - K.abs(mean_pred-mean_true)/mean_true, axis=-1)


# in vanilla network:
# https://arxiv.org/pdf/1709.05424.pdf, p. 3:
# We  replaced  the  last  layer  of  the  baseline  CNN  with  a
# fully-connected  layer  with  10  neurons  followed  by  soft-max
# activations 


'''
Vanilla network:
x1 = Dropout(rate=0.75)(base_model.layers[-1].output)
x = Dense(10, activation='softmax')(x1)

p.6

The baseline CNN weights are initialized by training on ImageNet [15], and the last fully-connected
layer is randomly initialized. The weight and bias momentums
are  set  to  0.9,  and  a  dropout  rate  of  0.75  is  applied  on  the
last  layer  of  the  baseline  network.  The  learning  rate  of  the
baseline  CNN  layers  and  the  last  fully-connected  layers  are
set as 3x10−7 and 3x10−6, respectively. We observed that
setting a low learning rate on baseline CNN layers results in
easier and faster optimization when using stochastic gradient
descent. Also, after every 10 epochs of training, an exponential
decay with decay factor 0.95 is applied to all learning rates.
'''

# set number of hidden units ~ half of embedding size.
lstm_units = 150
rate_drop_lstm = 0.2
rate_drop_dense = 0.2

embedding = Embedding(input_dim = embedding_matrix.shape[0],
        output_dim = WORD2VEC_EMBEDDING_DIM,
        weights=[embedding_matrix],
        input_length=MAX_SEQUENCE_LENGTH,
        trainable=False)
# shered lstm for all inputs
lstm = Bidirectional(LSTM(lstm_units, dropout=rate_drop_lstm, recurrent_dropout=rate_drop_lstm))


# make three inputs

sequence_1_input = Input(shape=(MAX_SEQUENCE_LENGTH,), dtype='int32')
score_1_input = Input(shape=(1,), dtype='float')
embedded_sequences_1 = embedding(sequence_1_input)
x1 = lstm(embedded_sequences_1)


sequence_2_input = Input(shape=(MAX_SEQUENCE_LENGTH,), dtype='int32')
score_2_input = Input(shape=(1,), dtype='float')
embedded_sequences_2 = embedding(sequence_2_input)
x2 = lstm(embedded_sequences_2)


sequence_3_input = Input(shape=(MAX_SEQUENCE_LENGTH,), dtype='int32')
score_3_input = Input(shape=(1,), dtype='float')
embedded_sequences_3 = embedding(sequence_3_input)
x3 = lstm(embedded_sequences_3)


merged = concatenate([x1, score_1_input, x2, score_2_input, x3, score_3_input])
merged = Dropout(rate_drop_dense)(merged)
merged = BatchNormalization()(merged)

# make one layer to think about LSTM features
z = Dense(512, activation='tanh')(merged)

# take input from base model
y = Dropout(rate=0.5)(base_model.layers[-2].output)
y = Dense(512, activation='tanh')(y)


# combine those
merged2 = concatenate([y,z])

# make predictions
t = Dropout(rate=0.5)(merged2)
t = BatchNormalization()(t)
t = Dense(10, activation='softmax')(t)


model = Model(inputs=[base_model.input, sequence_1_input, score_1_input, sequence_2_input, score_2_input, sequence_3_input, score_3_input], outputs=t)

print(model.summary())
## Pretrain ------------------------  (comment out if you continue!!)

# freeze all layers for pretrain
for layer in base_model.layers:
    layer.trainable = False

sgd = keras.optimizers.Adam(lr=0.001)

model.compile(loss=my_loss, optimizer=sgd, metrics=[earth_mover_loss, acc, bin_acc, first_moment, second_moment, pearson_corr_scores]) 

# checkpoint
checkpoint = ModelCheckpoint('weights-pretrain-{epoch:02d}-{val_bin_acc:.2f}.hdf5', monitor='val_loss', verbose=0, save_best_only=False, save_weights_only=False, mode='auto', period=1)


callbacks_list = [checkpoint]


train_seq = DataSequence(label_train, data_path,  batch_size=batch_size)
test_seq = DataSequence(label_test, data_path,  batch_size=batch_size)


model.fit_generator(train_seq,
          epochs=pretrain_epochs,
          verbose=1,
          shuffle=False,
          validation_data=test_seq,
          callbacks=callbacks_list,
          workers=32)

# ------------------------------------


# model.load_weights('...') # if you want to continue
# Fine-tune ------------------------

for layer in base_model.layers:
    layer.trainable = True

# see the Readme what lr to use there !
sgd = keras.optimizers.Adam(lr=0.00001)


model.compile(loss=my_loss, optimizer=sgd, metrics=[earth_mover_loss, acc, bin_acc, first_moment, second_moment, pearson_corr_scores]) 

# checkpoint. Save all checkpoins as validation does not improve !!
checkpoint = ModelCheckpoint('weights-continue4-{epoch:02d}-{val_bin_acc:.2f}.hdf5', monitor='val_loss', verbose=0, save_best_only=False, save_weights_only=False, mode='auto', period=1)

callbacks_list = [checkpoint]


train_seq = DataSequence(label_train, data_path,  batch_size=batch_size)
test_seq = DataSequence(label_test, data_path,  batch_size=batch_size)


model.fit_generator(train_seq,
          epochs=epochs,
          verbose=1,
          shuffle=False,
          validation_data=test_seq,
          callbacks=callbacks_list,
          workers=32)


'''
# ---------- Fine-tune L1

#model.load_weights('weights-continue3-01-0.79.hdf5')     

sgd = keras.optimizers.Adam(lr=0.0000001)


model.compile(loss=my_loss_L1, optimizer=sgd, metrics=[earth_mover_loss, acc, bin_acc, first_moment, second_moment]) 

# checkpoint. Save all checkpoins as validation does not improve !!
checkpoint = ModelCheckpoint('weights-continue5-{epoch:02d}-{val_bin_acc:.2f}.hdf5', monitor='val_loss', verbose=0, save_best_only=False, save_weights_only=False, mode='auto', period=1)

callbacks_list = [checkpoint]


train_seq = DataSequence(label_train, data_path,  batch_size=batch_size)
test_seq = DataSequence(label_test, data_path,  batch_size=batch_size)


model.fit_generator(train_seq,
          epochs=epochs,
          verbose=1,
          shuffle=False,
          validation_data=test_seq,
          callbacks=callbacks_list,
          workers=32)
'''


# validate ---------------------
val_gen = DataSequence(label_test, data_path,  batch_size=batch_size, mode='val')
scores = model.evaluate_generator(val_gen, workers=12, verbose=1)
print('EMD loss: {}, bin_acc:{}, chi-sq:{}'.format(scores[0], scores[1], scores[2])) # EMD loss: 0.07736995112838584, bin_acc:0.7642938206957468, chi-sq:7.629008602695736


# get all predictions ------------

val_gen = DataSequence(label_test, data_path,  batch_size=batch_size, mode='val')
all_predictions = model.predict_generator(val_gen, workers=12, verbose=1)

# save predictions to plot histogram later
with open('model_predictions_oversample.pickle', 'wb') as handle:
    pickle.dump(all_predictions, handle, protocol=pickle.HIGHEST_PROTOCOL)


