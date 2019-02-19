#! /usr/bin/python
"""
iotstream_lr_kafka.py: Spark streaming program to analyze data generated by sim_sensors_lr_kafka.py with Logistic Regression using Kafka input
  Outputs prediction of model based on input data

In one window:
  $ python sim_sensors_lr_kafka.py n_sensors average_sensor_events_per_second total_events kafka_server_list kafka_topic

In another window:
  $ spark-submit iotstream_lr_kafka.py n_sensors reporting_interval kafka_server_list kafka_topic HDFS_or_S3 HDFS_path_or_S3_bucket modelname

Copyright (c) 2018 VMware, Inc.

This product is licensed to you under the Apache 2.0 license (the "License").  You may not use this product except in compliance with the Apache 2.0 License.

This product may include a number of subcomponents with separate copyright notices and license terms. Your use of these subcomponents is subject to the terms and conditions of the subcomponent's license, as noted in the LICENSE file.
"""

from __future__ import print_function

import sys
import numpy as np
from time import time, gmtime, strftime, sleep
from pyspark import SparkContext
from pyspark.streaming import StreamingContext
from pyspark.streaming.kafka import KafkaUtils
from pyspark.mllib.classification import LogisticRegressionModel

if len(sys.argv) != 8:
    print("Usage: spark-submit iotstream_lr_kafka.py n_sensors reporting_interval kafka_server_list kafka_topic HDFS_or_S3 HDFS_path_or_S3_bucket modelname", file=sys.stderr)
    exit(-1)

n_sensors = int(sys.argv[1])
reporting_interval = float(sys.argv[2])
kafka_server_list = sys.argv[3]
topic    = sys.argv[4]

if sys.argv[5].capitalize() == 'S3':
  modelname = "s3a://{}/{}".format(sys.argv[6], sys.argv[7])
else:
  modelname = "{}/{}".format(sys.argv[6], sys.argv[7])

print('%s.%03dZ: Analyzing stream of input from kafka topic %s with kafka server(s) %s, using LR model %s, with %.1f second intervals' % (strftime("%Y-%m-%dT%H:%M:%S", gmtime()), (time()*1000)%1000, topic, kafka_server_list, modelname, reporting_interval))

def run_model(rdd):
  last_batch = False
# Input rdd consists of lines of sensor inputs received during that particular batch
# This code combines the lines in each batch into a feature vector containing the latest sensor values
# Don't start processing input until events start streaming
  if rdd.count() == 0:
    empty_intervals.add(1)
    print("No input")
  else:
  # Each line of input has format Timestamp (string), sensor number (integer), sensor name (string), sensor value (float), eg
  # 2017-12-14T22:22:43.895Z,19,Sensor 19,0.947640
  # Split each line into its fields, filter out any lines that are not the expected length, then 
  #  create a list of tuples with each tuple representing (sensor number, sensor value)
    input = rdd.map(lambda offset_line: offset_line[1]).map(lambda line: line.split(',')).filter(lambda list: len(list) == 4).map(lambda list: (int(list[1]), float(list[3]))).collect()
  # Read input into features vector. If a sensor was not read during this interval its current value will persist
    for t in input:
      if t[0] < 0:
        last_batch = True
      features[t[0]-1] = t[1]
    interval.add(1)
    events.add(len(input))
  # If model predicts True warn user in red
    if (model.predict(features)):
      print('\033[31m%s.%03dZ: Interval %d: Attention needed (%d sensor events in interval)\033[0m' % (strftime("%Y-%m-%dT%H:%M:%S", gmtime()), (time()*1000)%1000, interval.value, len(input)))
    else:
      print('%s.%03dZ: Interval %d: Everything is OK (%d sensor events in interval)' % (strftime("%Y-%m-%dT%H:%M:%S", gmtime()), (time()*1000)%1000, interval.value, len(input)))
    if last_batch:
      ssc.stop()

# Initialize features to <number of sensors>-length array, filled with neutral initial sensor value
features = np.zeros(n_sensors)
features.fill(0.5) 

# Initialize streaming for specified reporting interval
sc = SparkContext(appName="iotstream_lr_kafka")
interval = sc.accumulator(0)
empty_intervals = sc.accumulator(0)
events  = sc.accumulator(0)
ssc = StreamingContext(sc, reporting_interval)
sensor_stream = KafkaUtils.createDirectStream(ssc, [topic], {"bootstrap.servers": kafka_server_list})

# Load pre-computed model
model = LogisticRegressionModel.load(sc, modelname)

# Run model on each batch
#sensor_stream.pprint(10)
sensor_stream.foreachRDD(run_model)

# Start reading streaming data
ssc.start()
start_time = time()
ssc.awaitTermination()
finish_time = time()
elapsed_time = finish_time - start_time - empty_intervals.value*reporting_interval - 1.5 # Subtract off time waiting for events and 1.5 sec for termination
print('\n%s.%03dZ: %d events received in %.1f seconds (%d intervals), or %.0f sensor events/second\n' % (strftime("%Y-%m-%dT%H:%M:%S", gmtime()), (time()*1000)%1000, events.value-1,  elapsed_time, interval.value, float(events.value-1)/elapsed_time))
