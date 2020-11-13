#!/usr/bin/env python3
# -*- coding: utf-8 -*-  
# ############################################################################################
# AUTHOR: Michael Gallagher (CIRES/NOAA)
# EMAIL:  michael.r.gallagher@noaa.gov
# 
# This script takes in the 'slow' level1 data and makes plots of a suite of variables. Each
# plot is given a general name (e.g. meteorology) and then an associated dictionary controls
# the number of subplots and the variables that go on each subplot. 
#
# The data ingest and the plots are done in parallel, so your lap could get a little hot...
# ... but it means the full year of data and make *all* of the daily plots in less than 20
# minutes on an SSD based system. Slower for rusty stuff. You can do this too by running:
#
# /usr/bin/time --format='%C ran in %e seconds' ./plot_asfs_lev1_quicklooks.py -v -s 20191005 -e 20201002 
#
# This scripts requires 4+ threads so if you do this on a dual-core system it's going to be
# a little disappointing.
# 
#
# DATES:
#   v1.0: 2020-11-13
# 
# ############################################################################################

from datetime  import datetime, timedelta

from multiprocessing import Process as P
from multiprocessing import Queue   as Q

import os, inspect, argparse, sys
import matplotlib as mpl
import matplotlib.pyplot as plt
import colorsys

# this is here because for some reason the default matplotlib doesn't
# like running headless...  off with its head
mpl.use('pdf');
mpl.interactive(False)

plt.ioff() # turn off pyplot interactive mode 
os.environ['HDF5_USE_FILE_LOCKING']='FALSE'  # just in case
os.environ['HDF5_MPI_OPT_TYPES']='TRUE'  # just in case

import numpy  as np
import pandas as pd
import xarray as xr

sys.path.insert(0,'../')

import functions_library as fl 

#import warnings
mpl.warnings.filterwarnings("ignore", category=mpl.MatplotlibDeprecationWarning) 

def main(): # the main data crunching program

    default_data_dir = '/psd3data/arctic/MOSAiC/' # give '-p your_directory' to the script if you don't like this

    make_daily_plots = True
    make_leg_plots   = True # make plots that include data from each leg

    leg1_start = datetime(2019,10,5)
    leg2_start = datetime(2019,12,15) 
    leg3_start = datetime(2020,3,2)
    leg4_start = datetime(2020,6,1)
    leg5_start = datetime(2020,8,15)
    mosaic_end = datetime(2020,10,2)
    leg_list   = [leg1_start,leg2_start,leg3_start,leg4_start,leg5_start,mosaic_end]

    global sleds_to_plot, code_version # code_version is the *production* code and is pulled in from nc files later
    sleds_to_plot = ('asfs30','asfs40','asfs50')

    # what are we plotting? dict key is the full plot name, value is another dict...
    # ... of subplot titles and the variables to put on each subplot
    var_dict = {}
    var_dict['meteorology']     = {'temperature'      : ['apogee_targ_T_Avg','vaisala_T_Avg'],
                                   'humidity'         : ['vaisala_RH_Avg'],
                                   'pressure'         : ['vaisala_P_Avg'],
                                   }
    var_dict['winds']           = {'winds_horizontal' : ['metek_horiz_Avg'], # CREATED BELOW
                                   'winds_vertical'   : ['metek_z_Avg'],
                                   }
    var_dict['radiation']       = {'shortwave'        : ['sr30_swu_Irr_Avg','sr30_swd_Irr_Avg'], 
                                   'longwave'         : ['ir20_lwu_Wm2_Avg','ir20_lwd_Wm2_Avg'], 
                                   'net'              : ['net_Irr_Avg'], # CREATED BELOW
                                   }
    var_dict['plates_and_sr50'] = {'flux_plates'      : ['fp_A_Wm2_Avg','fp_B_Wm2_Avg'],
                                   'surface_distance' : ['sr50_dist_Avg'],
                                   }
    var_dict['is_alive']        = {'logger_temp'      : ['PTemp_Avg'],
                                   'logger_voltage'   : ['batt_volt_Avg'],
                                   }

    unit_dict = {}
    unit_dict['meteorology']     = {'temperature'      : 'C',
                                    'humidity'         : '%', 
                                    'pressure'         : 'hPa', 
                                    }
    unit_dict['winds']           = {'winds_horizontal' : 'm/s', 
                                    'winds_vertical'   : 'm/s', 
                                    }
    unit_dict['radiation']       = {'shortwave'        : 'W/m2', 
                                    'longwave'         : 'W/m2', 
                                    'net'              : 'W/m2', 
                                    }
    unit_dict['plates_and_sr50'] = {'flux_plates'      : 'W/m2', 
                                    'surface_distance' : 'm', 
                                    }
    unit_dict['is_alive']        = {'logger_temp'      : 'C', 
                                    'logger_voltage'   : 'V', 
                                    }

    # if you put a color in the list, (rgb or hex) the function below will all lines different luminosities
    # of the same hue. if you put a 3-tuple of colors, it will use the colors provided explicitly for 30/40/50
    color_dict = {}
    color_dict['meteorology']     = ['#E24A33','#348ABD','#988ED5','#777777','#FBC15E','#8EBA42','#FFB5B8']
    color_dict['winds']           = ['#4878CF','#6ACC65','#D65F5F','#B47CC7','#C4AD66','#77BEDB','#4878CF']
    color_dict['radiation']       = ['#001C7F','#017517','#8C0900','#7600A1','#B8860B','#006374','#001C7F']
    color_dict['plates_and_sr50'] = ['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2']
    color_dict['is_alive']        = [((0.8,0.8,0.9), (0.35,0.55,0.55), (0.55,0.55,0.35)), (0.2,0.5,0.8)]

    # gg_colors    = ['#E24A33','#348ABD','#988ED5','#777777','#FBC15E','#8EBA42','#FFB5B8']
    # muted_colors = ['#4878CF','#6ACC65','#D65F5F','#B47CC7','#C4AD66','#77BEDB','#4878CF']
    # dark_colors  = ['#001C7F','#017517','#8C0900','#7600A1','#B8860B','#006374','#001C7F']
    # other_dark   = ['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2']
    # other_colors = [(0.8,0.8,0.9), (0.85,0.85,0.9), (0.9,0.9,1.0)]

    parser = argparse.ArgumentParser()                                
    parser.add_argument('-v', '--verbose',    action ='count', help='print verbose log messages')            
    parser.add_argument('-s', '--start_time', metavar='str',   help='beginning of processing period, Ymd syntax')
    parser.add_argument('-e', '--end_time',   metavar='str',   help='end  of processing period, Ymd syntax')
    parser.add_argument('-p', '--path', metavar='str', help='base path to data up to, including /data/, include trailing slash')

    args         = parser.parse_args()
    v_print      = print if args.verbose else lambda *a, **k: None
    verboseprint = v_print

    global data_dir, level1_dir # paths
    if args.path: data_dir = args.path
    else: data_dir = default_data_dir
    
    start_time = datetime.today()
    if args.start_time: start_time = datetime.strptime(args.start_time, '%Y%m%d') 
    else: # make the data processing start yesterday! i.e. process only most recent full day of data
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0, day=start_time.day-1) 
    if args.end_time: end_time = datetime.strptime(args.end_time, '%Y%m%d')   
    else: end_time = start_time

    print('---------------------------------------------------------------------------------------')
    print('Plotting data days between {} -----> {}'.format(start_time,end_time))
    print('---------------------------------------------------------------------------------------\n')

    quicklooks_dir   = '{}/quicklooks/asfs/1_level/'.format(data_dir)
    out_dir_daily    = '{}/daily/'.format(quicklooks_dir)    # where you want to put the png
    out_dir_all_days = '{}/all_days/'.format(quicklooks_dir) # where you want to put the png

    # plot for all of leg 2.
    day_series = pd.date_range(start_time, end_time) # we're going to get date for these days between start->end

    df_list = []
    print(" Retreiving data from netcdf files...")    
    for i_day, today in enumerate(day_series): # loop over the days in the processing range and get a list of files
        df_today = pd.DataFrame()
        q_dict = {}
        p_dict = {}
        df_dict = {}
        for istation, curr_station in enumerate(sleds_to_plot):
            if i_day % 1 == 0 and istation == 0: print("  ... getting data for day {}".format(today))
            site_strs ={'asfs30':'L2','asfs40':'L1','asfs50':'L3'}
            #file_str_slow = '/mos{}slow.level1.{}.nc'.format(curr_station, today.strftime('%Y%m%d.%H%M%S'))
            file_str_slow = '/slow_preliminary_{}.{}.{}.nc'.format(curr_station, site_strs[curr_station],today.strftime('%Y%m%d'))
            level1_dir    = data_dir+curr_station+'/1_level_ingest_{}/'.format(curr_station) # where does level1 data live?
            curr_file     = level1_dir+file_str_slow


            q_dict[curr_station] = Q()
            p_dict[curr_station] = P(target=get_asfs_data, \
                                     args=(curr_file, curr_station, today, \
                                           q_dict[curr_station])).start()
 
        for istation, curr_station in enumerate(sleds_to_plot):
            df_dict[curr_station] = q_dict[curr_station].get()
            cv = q_dict[curr_station].get()
            if cv!=None: code_version = cv

        for istation, curr_station in enumerate(sleds_to_plot):
            if df_today.empty: df_today = df_dict[curr_station]
            else:              df_today = pd.concat( [df_today, df_dict[curr_station]], axis=1 )

        df_list.append(df_today.copy())

    df = pd.concat(df_list)
    time_dates = df.index
    df['time'] = time_dates # duplicates index... but it can be convenient

    print('\n ... data sample :')
    print('================')
    print(df)
    print('\n')
    print(df.info())
    #for var in df.columns.values.tolist(): print('   {}'.format(var))
    print('================\n\n') 

    ## create variables that we want to have 
    for istation, curr_station in enumerate(sleds_to_plot):
        df['net_Irr_Avg_{}'.format(curr_station)] = \
           df['sr30_swu_Irr_Avg_{}'.format(curr_station)] \
          -df['sr30_swd_Irr_Avg_{}'.format(curr_station)] \
          +df['ir20_lwu_Wm2_Avg_{}'.format(curr_station)] \
          -df['ir20_lwd_Wm2_Avg_{}'.format(curr_station)]

        df['metek_horiz_Avg_{}'.format(curr_station)] = \
          np.sqrt(df['metek_x_Avg_{}'.format(curr_station)]*df['metek_x_Avg_{}'.format(curr_station)]+
                  df['metek_y_Avg_{}'.format(curr_station)]*df['metek_y_Avg_{}'.format(curr_station)])

    make_plots_pretty('seaborn-whitegrid') # ... and higher resolution

    if make_daily_plots:
        day_delta  = pd.to_timedelta(86399999999,unit='us') # we want to go up to but not including 00:00
        print("~~ making daily plots for all figures ~~")
        print("----------------------------------------")
        for iday, today in enumerate(day_series):
            if iday%1==0: print("... plotting for day {}".format(today))
            tomorrow  = today+day_delta
            start_str = today.strftime('%Y-%m-%d') # get date string for file name
            end_str   = (today+timedelta(1)).strftime('%Y-%m-%d')   # get date string for file name

            ifig = -1
            plot_q_dict = {}; plot_p_dict = {}
            for plot_name, subplot_dict in var_dict.items():
                ifig += 1; plot_q_dict[plot_name] = Q()
                save_str  ='{}/plot_name/MOSAiC_ASFS_{}_{}_to_{}.png'.format(out_dir_daily, plot_name, start_str, end_str)

                plot_p_dict[plot_name] = P(target=make_plot,
                                           args=(df[today:tomorrow].copy(), subplot_dict, unit_dict[plot_name],
                                                 color_dict[plot_name],save_str,True,plot_q_dict[plot_name])).start()

            for plot_name, subplot_dict in var_dict.items():
                plot_q_dict[plot_name].get()

    make_plots_pretty('ggplot')
    if make_leg_plots:
        leg_names = ["leg1","leg2","leg3","leg4","leg5"]
        for ileg in range(0,len(leg_list)-1):
            leg_dir   = "{}/{}_complete".format(quicklooks_dir,leg_names[ileg])
            start_day = leg_list[ileg]; start_str = start_day.strftime('%Y-%m-%d') # get date string for file name
            end_day   = leg_list[ileg+1]; end_str = end_day.strftime('%Y-%m-%d')   # get date string for file name

            ifig = -1
            plot_q_dict = {}; plot_p_dict = {}
            for plot_name, subplot_dict in var_dict.items():
                ifig += 1; plot_q_dict[plot_name] = Q()
                save_str  ='{}/MOSAiC_ASFS_{}_{}_to_{}.png'.format(leg_dir, plot_name, start_str, end_str)
                plot_p_dict[plot_name] = P(target=make_plot,
                                           args=(df[start_day:end_day].copy(),subplot_dict,unit_dict[plot_name],
                                                 color_dict[plot_name],save_str, False,plot_q_dict[plot_name])).start()

            for plot_name, subplot_dict in var_dict.items():
                plot_q_dict[plot_name].get()

    # make plots for range *actually* requested when calling scripts
    start_str = start_time.strftime('%Y-%m-%d') # get date string for file name
    end_str   = end_time.strftime('%Y-%m-%d')   # get date string for file name

    ifig = -1
    plot_q_dict = {}; plot_p_dict = {}
    for plot_name, subplot_dict in var_dict.items():
        ifig += 1; plot_q_dict[plot_name] = Q()
        save_str  ='{}/MOSAiC_ASFS_{}_{}_to_{}.png'.format(out_dir_all_days, plot_name, start_str, end_str)
        plot_p_dict[plot_name] = P(target=make_plot,
                                   args=(df[start_time:end_time].copy(), subplot_dict, unit_dict[plot_name],
                                         color_dict[plot_name], save_str,False,plot_q_dict[plot_name])).start()

    for plot_name, subplot_dict in var_dict.items():
        plot_q_dict[plot_name].get()

    plt.close('all') # closes figure before looping again 
    exit() # end main()

def get_asfs_data(curr_file, curr_station, today, q):

    if os.path.isfile(curr_file):
        xarr_ds = xr.open_dataset(curr_file)
        data_frame = xarr_ds.to_dataframe()
        data_frame = data_frame.add_suffix('_{}'.format(curr_station))
        code_version = xarr_ds.attrs['version']
    else:
        print(' !!! file {} not found for date {}'.format(curr_file,today))
        data_frame   = pd.DataFrame()
        code_version = None
    q.put(data_frame)
    q.put(code_version)
    return # can be implicit

# abstract plotting to function so plots are made iteratively according to the keys and values in subplot_dict and
# the supplied df and df.index.... i.e. this plots the full length of time available in the supplied df
def make_plot(df, subplot_dict, units, colors, save_str, daily, q):

    nsubs = len(subplot_dict)
    if daily: fig, ax = plt.subplots(nsubs,1,figsize=(80,40*nsubs))  # square-ish, for daily detail
    else:     fig, ax = plt.subplots(nsubs,1,figsize=(160,30*nsubs)) # more oblong for long time series

    # loop over subplot list and plot all variables for each subplot
    ivar = -1; isub = -1
    for subplot_name, var_list in subplot_dict.items():
        isub+=1
        legend_additions = [] # uncomment code below to add the percent of missing data to the legend

        for var in var_list:
            ivar+=1
            if isinstance(colors[ivar],str) or isinstance(colors[ivar][0],float) :
                color_tuples = get_rgb_trio(colors[ivar])
            else: color_tuples = list(colors[ivar])

            for istation, curr_station in enumerate(sleds_to_plot):
                try:
                    asfs_var   = var+'_{}'.format(curr_station)
                    asfs_color = color_tuples[istation]
                    perc_miss  = fl.perc_missing(df[asfs_var])

                    time_lims = (df.index[0], df.index[-1]+(df.index[-1]-df.index[-2])) 
                    df[asfs_var].plot(xlim=time_lims, ax=ax[isub], color=asfs_color)
                    legend_additions.append('{} (missing '.format(asfs_var)+str(perc_miss)+'%)')
                    plot_success = True

                except Exception as e:
                    legend_additions.append('{} (no data)'.format(asfs_var))
                    continue

        #add useful data info to legend
        j = 0 
        h,l = ax[isub].get_legend_handles_labels()
        for s in range(0,len(l)):
            l[s] = legend_additions[s]

        #ax[isub].legend(l, loc='upper right',facecolor=(0.3,0.3,0.3,0.5),edgecolor='white')
        ax[isub].legend(l, loc='best',facecolor=(0.3,0.3,0.3,0.5),edgecolor='white')    
        ax[isub].set_ylabel('{} [{}]'.format(subplot_name, units[subplot_name]))
        ax[isub].grid(b=True, which='major', color='grey', linestyle='-')
        #ax[isub].grid(b=False, which='minor')

        if isub==len(subplot_dict)-1:
            ax[isub].set_xlabel('date [UTC]', labelpad=-0)
        else:
            ax[isub].tick_params(which='both',labelbottom=False)
            ax[isub].set_xlabel('', labelpad=-200)

    fig.text(0.5, 0.005,'(plotted on {} from level1 data version {} )'.format(datetime.today(), code_version),
             ha='center')

    fig.tight_layout(pad=0.4)
    #fig.tight_layout(pad=5.0) # cut off white-space on edges

    #print('... saving to: {}'.format(save_str))
    if not os.path.isdir(os.path.dirname(save_str)):
        print("!!! making directory {}... hope that's what you intended".format(os.path.dirname(save_str)))
        os.makedirs(os.path.dirname(save_str))

    fig.savefig(save_str)
        
    plt.close() # closes figure before exiting
    q.put(True)
    return # not necessary

# returns 3 rgb tuples of varying darkness for a given color, 
def get_rgb_trio(color):
    if isinstance(color, str):
        rgb = hex_to_rgb(color)
    else: rgb = color
    r=rgb[0]; g=rgb[1]; b=rgb[2]
    lume = np.sqrt(0.299*r**22 + 0.587*g**2 + 0.114*b**2)
    h,l,s = colorsys.rgb_to_hls(r,g,b)
    if(lume>0.5): 
        col_one = colorsys.hls_to_rgb(h, l, s)
        col_two = colorsys.hls_to_rgb(h, l-0.2, s)
        col_thr = colorsys.hls_to_rgb(h, l-0.4, s)
    else:
        col_one = colorsys.hls_to_rgb(h, l+0.4, s)
        col_two = colorsys.hls_to_rgb(h, l+0.2, s)
        col_thr = colorsys.hls_to_rgb(h, l, s)
    return [col_one, col_two, col_thr]

def hex_to_rgb(hex_color):
    rgb_tuple = tuple(int(hex_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    return tuple(map(lambda x: x/256.0, rgb_tuple))

def make_plots_pretty(style_name):
    # plt.style.use('ggplot')            # grey grid with bolder colors
    # plt.style.use('seaborn-whitegrid') # white grid with softer colors
    plt.style.use(style_name)

    mpl.rcParams['lines.linewidth']     = 6
    mpl.rcParams['font.size']           = 70
    mpl.rcParams['legend.fontsize']     = 'medium'
    mpl.rcParams['axes.labelsize']      = 'xx-large'
    mpl.rcParams['axes.titlesize']      = 'xx-large'
    mpl.rcParams['xtick.labelsize']     = 'xx-large'
    mpl.rcParams['ytick.labelsize']     = 'xx-large'
    mpl.rcParams['ytick.labelsize']     = 'xx-large'
    mpl.rcParams['grid.linewidth']      = 2.
    mpl.rcParams['axes.linewidth']      = 6
    mpl.rcParams['axes.grid']           = True
    mpl.rcParams['axes.grid.which']     = 'minor'
    mpl.rcParams['axes.edgecolor']      = 'grey'
    mpl.rcParams['axes.labelpad']       = 100
    mpl.rcParams['axes.titlepad']       = 100
    mpl.rcParams['axes.xmargin']        = 0.3
    mpl.rcParams['axes.ymargin']        = 0.3
    mpl.rcParams['xtick.major.pad']     = 10
    mpl.rcParams['ytick.major.pad']     = 10
    mpl.rcParams['xtick.minor.pad']     = 10
    mpl.rcParams['ytick.minor.pad']     = 10
    mpl.rcParams['xtick.minor.visible'] = True
    mpl.rcParams['axes.spines.right']   = False
    mpl.rcParams['axes.spines.top']     = False
    mpl.rcParams['legend.facecolor']    = 'white'

# this runs the function main as the main program... this is a hack that allows functions
# to come after the main code so it presents in a more logical, C-like, way 
if __name__ == '__main__': 
    main() 

