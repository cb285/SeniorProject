#!/usr/bin/env python3

# USAGE: ./power_plotter.py <csv_filename>"

import sys
import os.path
import plotly
import plotly.graph_objs as go
import pandas as pd
from datetime import datetime

TIME_COL_NAME = "time"
Y_AXIS_COL_NAME = "power_usage"

def main(args):
    # if no args given show usage
    if (len(args) != 2):
        print ("USAGE: " + args[0] + " <csv_filename>")
        return
        
    # see if file exists
    if (not os.path.isfile(args[1])):
        print ("ERROR: csv file does not exist")
        return
    
    # read data from file
    try:
        inputData = pd.read_csv(args[1])
    except:
        inputData = pd.read_excel(args[1])
        
    # convert it to a time/date if found
    if TIME_COL_NAME in inputData.columns:
        inputData[TIME_COL_NAME] =  pd.to_datetime(inputData[TIME_COL_NAME])
    else:
        print("time column" + "\"" + str(TIME_COL_NAME) + "\" not found in file")
        return

    devices = dict()
    
    #for row in inputData.rows:
    #    devices.
    
    y_labels = [Y_AXIS_COL_NAME]
    
    # setup figure
    fig = plotly.tools.make_subplots(rows=1, cols=1, shared_xaxes=True, print_grid=False)
    
    # set title to input filename
    fig["layout"].update(title=args[1])

    trace_num = 1
    
    # create each subplot
    for y_label in y_labels:
        print("y_label = " + str(y_label))
        a_trace = go.Scatter(
            x = inputData[TIME_COL_NAME],
            y = inputData[y_label],
            mode = "lines",
            name = y_label,)
        
        # add subplot to figure
        fig.append_trace(a_trace, trace_num, 1)
        trace_num += 1 # increment trace counter
        
    # plot the figure
    plotly.offline.plot(fig, filename="".join(args[1].split(".")[:-1]) + "-GRAPH.html")

    # calulate averages
    print ("Averages:")
    print (inputData.mean(axis=0))
    
# run
if __name__ == "__main__":
    main(sys.argv)
