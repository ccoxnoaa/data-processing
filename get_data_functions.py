import os

from datetime  import datetime, timedelta

import pandas as pd
import xarray as xr
import numpy  as np

from multiprocessing import Process as P
from multiprocessing import Queue   as Q

def get_flux_data(station, start_day, end_day, level,
                  data_dir='/Projects/MOSAiC/', data_type='slow',
                  verbose=False, nthreads=1, pickle_dir=None):

    """ Get a dataset from the MOSAiC flux project. 

    Function assumes the standard folder structure as in the NOAA archive. 
    Supports parallelism without using heavy libraries, like dask. 

    Required params
    ---------------
    station     : str station name, used to determine directory and file name, 'asfs30', etc 'tower'
    start_day   : datetime object, used to determine file names
    end_day     : datetime object, used to determine when to stop
    level       : 1, 2, ... which dataset 

    Optional params
    ---------------
    data_dir    : the head where the files can be found
    data_type   : 'fast' 'slow', 'turb' data, etc
    nthreads    : how many cpu threads would you like to use 
    verbose     : would you like to see more print statements?

    pickle_dir : if provided, we search for a pandas 'pickle' binary
                 file containing the pre-packed pandas objects. if we
                 don't find it, it is written after ingest. saves *a lot*
                 of time when stored on ramdisk for bigger files.

    Returns
    -------
    tuple (df pandas.DataFrame, str code_version)

             df contains all data between requested days 
             code version is read from file netcdf attributes

    """

    station_list = ['tower','asfs30','asfs40','asfs50']

    if not any(station == name for name in station_list):
        print("\n\nYou asked for a station name that doesn't exist...")
        print("... can't help you here\n\n"); raise IOError

    pickled_filename = f'{station}_{level}_{data_type}_df' # code_version is tacked on to this when run
    df = pd.DataFrame() # dataframe and version we return from this function
    code_version = "?"
    was_pickled = False
    if pickle_dir:
        print(f"\n!!! searching for pickle file containing {pickled_filename} and loading it, takes time...\n")
        for root, dirs, files in os.walk(pickle_dir): # pretty stupid way to find the file
            for filename in files:
                if pickled_filename in filename:
                    filename = pickle_dir+ filename
                    df = pd.read_pickle(filename)
                    name_words = filename.rpartition('_')[-1].rpartition('.')
                    code_version = f"{name_words[0]}.{name_words[1]}"
                    was_pickled = True
                    print(f" ... found and loaded pickle {filename} \n\n")
                    break

        if not was_pickled: print("... didn't find a pickle, we'll write one !!!\n\n")

    if not was_pickled: 
        df_list = [] # data frames get appended here in loop and then concatted by function after
        day_series = pd.date_range(start_day, end_day) 

        q_list = []; p_list = []; day_list = []
        for i_day, today in enumerate(day_series): # loop over days in processing range and get list of files

            if i_day %nthreads == 0:
                print("  ... getting data for day {} (and {} days after in parallel)".format(today,nthreads))

            date_str = today.strftime('%Y%m%d.%H%M%S')
            if level == 1: 
                level_str = 'ingest'

            subdir   = f'/{level}_level_{level_str}_{station}/'
            file_str = f'/mos{station}{data_type}.level{level}.{date_str}.nc'
            if station == 'tower':
                subdir   = f'/{level}_level_{level_str}/'
                file_str = f'/mosflx{station}{data_type}.level{level}.{date_str}.nc'

            if level == 2: level_str = 'product'
            if level == 3: level_str = 'archive'

            files_dir = data_dir+station+subdir
            curr_file = files_dir+file_str

            q_today = Q()
            P(target=get_datafile, args=(curr_file, station, today,q_today),).start()
            q_list.append(q_today)
            day_list.append(today)
            if (i_day+1) % nthreads == 0 or today == day_series[-1]:
                for qq in q_list:
                    df_today = qq.get()
                    cv = qq.get()
                    if cv!=None: code_version = cv # assume all files have same code version, save only one
                    if not df_today.empty: 
                        df_list.append(df_today.copy())
                q_list = []
                day_list = []

        if verbose: print("... concatting, takes some time...")
        try    : df = pd.concat(df_list)
        except : pd.DataFrame()

        time_dates = df.index
        df['time'] = time_dates # duplicates index... but it can be convenient

        if verbose:
            print('\n ... data sample :')
            print('================')
            print(df)
            print('\n')
            print(df.info())
            print('================\n\n') 

        if pickle_dir:
            print("\n\n!!! You requested to pickle the dataframe for speed !!!")
            print(f"... right now we're writing it to this directory {pickled_filename}")
            print("... copy this manually to a ramdisk somewhere for bonus speed points")
            print("... must be symlinked here to be seen by this routine")
            print("...\n... this takes a minute, patience\n\n")
            df.to_pickle(f"{pickle_dir}/{pickled_filename}_{code_version[0:3]}.pkl")

    return df, code_version 

def get_datafile(curr_file, curr_station, today, q):

    if os.path.isfile(curr_file):
        xarr_ds = xr.open_dataset(curr_file)
        data_frame = xarr_ds.to_dataframe()
        code_version = xarr_ds.attrs['version']
    else:
        print(f"!!! requested file doesn't exist : {curr_file}")
        data_frame   = pd.DataFrame()
        code_version = None

    q.put(data_frame)
    q.put(code_version)
    return # can be implicit but doesn't matter, really
