# use models's validation dataset to save labels + model predictions 

# I do not use generator there, as some files are missing and I want to make absolutely sure the results correspond


# Use tensorflow >= 1.10.0 to load this model. I had weird errors.

from os import path
import numpy as np
import pandas as pd
import cv2

from keras.preprocessing.image import load_img
from keras.preprocessing.image import img_to_array

import keras
from keras import backend as K
from keras.models import Model
from keras.layers import Dense, Dropout, Concatenate, Flatten
import tensorflow as tf

from scipy.io import savemat


base_model = keras.applications.mobilenet.MobileNet((224, 224, 3), pooling='avg', include_top=False, weights=None)
    
x = Dropout(0.75)(base_model.output)
x = Dense(10, activation='softmax')(x)

model = Model(inputs=base_model.input, outputs=x)

model.load_weights(path.join(path.dirname(path.abspath(__file__)),'models/MobileNet/weights_mobilenet_aesthetic_0.07.hdf5'))

print(model.summary())

print('loaded model')

'''
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
'''
# store elements of distribution to compute means, etc
dist_values = np.array([1,2,3,4,5,6,7,8,9,10], dtype=np.float32)
dist_values = np.expand_dims(dist_values, -1)

def mean_std(x):
    mean = x.dot(dist_values)
    # sqrt( E(X^2) - (E(X))^2 )
    return mean, np.sqrt(x.dot(dist_values**2) - mean**2 )


# predict scores  - use this function to evaluate your images -------------------------------------------
def test_inference(filename, model=model):
    # load an image in PIL format
    original = load_img(filename, target_size=(224, 224))
    numpy_image = img_to_array(original)
    
    numpy_image_n = keras.applications.mobilenet.preprocess_input(numpy_image.copy())

    # (1, 224, 224, 3)
    image_batch = np.expand_dims(numpy_image_n, axis=0)
    
    # get the predicted probabilities for each class
    predictions = model.predict(image_batch)

    mean, std = mean_std(predictions)
    
    return mean, std, predictions


# initial processing and saving predictions:


# load model validation data
import json

with open('data/AVA/ava_labels_test.json', 'r') as f:
    data = json.load(f)
    
label_test = []
for value in data:
    label_test.append([value["image_id"]]+value["label"])
    
label_test = np.array(label_test, dtype=float)
# normalize histograms
histograms = label_test[:,1:]
histograms /=  histograms.sum(axis=1)[:,np.newaxis]

# First column is id, other 10 - histogram
label_test[:,1:] = histograms

data_path = '../../datasets/AVA_dataset/images/images'



labels_good = []
predictions = []
mean_predictions = []
std_predictions = []

# process images one by one, saving predictions

for idx, image_id in enumerate(label_test[:,0]):
    filename = data_path +'/' + str(int(image_id)) + '.jpg'
    try:
        mean, std, pred = test_inference(filename)
    except:
        continue
    
    labels_good.append(label_test[idx])
    predictions.append(pred)
    
    mean_predictions.append(mean)
    std_predictions.append(std)
    
    if idx%100==0:
        print(idx)
        #print(pred)



# save all predictions
labels_good = np.array(labels_good)
predictions = np.array(predictions)
mean_predictions = np.array(mean_predictions)
std_predictions = np.array(std_predictions)

savemat('wtf_idealo_ava.mat', {'labels':labels_good, 'predictions':predictions, 'mean_predictions':mean_predictions, 'std_predictions':std_predictions})


