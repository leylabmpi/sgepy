import os
import sys
import re
import time
import uuid
import shutil
import logging
import subprocess as sp
import multiprocessing as mp
try:
    import dill as pickle
except:
    import pickle
  
class Worker():
    def __init__(self, parallel_env='parallel', threads=1, time='00:59:00',
                 mem='6G', gpu=0, tmp_dir=None, conda_env='snakemake',
                 keep_tmp=False, verbose=False):
        self.parallel_env=parallel_env
        self.threads = threads
        self.time = time
        self.mem = mem
        self.gpu = gpu
        self.tmp_dir = tmp_dir
        self.conda_env = conda_env
        self.verbose = verbose
        self.keep_tmp = keep_tmp
        self.param_file = None
        self.python_script_file = None
        self.bash_script_file = None
        self.results_file = None
        self.stdout_file = None
        self.stderr_file = None
        self.jobid = None

    def run(self, func, args=[], kwargs=dict(), pkgs=[]):
        """
        Main job run function
        """
        # serialize
        self.serialize(func, args, kwargs, pkgs)
        # job script
        self.job_python_script()
        self.job_bash_script()
        # qsub
        self.qsub()
        # check job
        while(1):
            ret = self.check_job()
            if ret == 'failed':
                # TODO: job resource excalation
                raise ValueError('job failed: {}'.format(self.jobid))
            elif ret == 'success':
                ret = pickle.load(open(self.results_file, 'rb'))
            else:
                raise ValueError('job check ret value not recognized: {}'.format(ret))
            # clean up
            if self.keep_tmp is False:
                self.clean_up()
            return ret

    def clean_up(self):
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
        if self.verbose:
            logging.info('tmp dir removed: {}'.format(self.tmp_dir))

    def check_job(self):
        regex = re.compile(r' +')
        delay = 1
        while(1):
            # time delay between checks
            time.sleep(delay)
            if delay < 120:
                delay = delay * 1.5
            else:
                delay = 120            
            # qstat
            ret = self.qstat_check(regex)
            if ret is None:
                pass
            elif ret == 'failed':
                sys.stderr('job faild: {}'.format(self.jobid))
            elif ret == 'running':
                continue
            # qacct 
            ret = self.qacct_check(regex)
            if ret is None:
                continue
            else:
                return ret
            
    def qstat_check(self, regex):
        if self.verbose:
            logging.info('qstat check: {}'.format(self.jobid))                  
        p = sp.Popen(['qstat'], stdout=sp.PIPE)
        output, err = p.communicate()
        if p.returncode != 0:
            return None
        for x in output.decode().split('\n'):
            y = re.split(regex, x)
            if y[0] == self.jobid:
                if y[4] in ['r', 'qw', 't']:
                    return 'running'
                elif y[4] in ['Eqw', 'd']:
                    return 'failed'
                else:
                    return 'running'
        return None

    def qacct_check(self, regex):
        if self.verbose:
            logging.info('qacct check: {}'.format(self.jobid))                           
        cmd = 'qacct -j {jobid}'.format(jobid=self.jobid)
        p = sp.Popen([cmd], stdout=sp.PIPE, shell=True, stderr=sp.DEVNULL)
        output, err = p.communicate()
        if p.returncode != 0:
            return None
        for x in output.decode().split('\n'):
            x = regex.split(x)
            if x[0] == 'exit_status':
                if x[1] == '0':
                    return 'success'
                else:
                    return 'failed'
        return None
                
    def qsub(self):
        """
        formatting qsub command
        """
        self.stdout_file = os.path.join(self.tmp_dir, 'stdout.txt')
        self.stderr_file = os.path.join(self.tmp_dir, 'stderr.txt')
        cmd = 'qsub -cwd -pe {par_env} {threads} -l h_vmem={mem} -l h_rt={time} -l gpu={gpu} -o {std_out} -e {std_err} {job_script}'
        cmd = cmd.format(par_env=self.parallel_env,
                         threads=self.threads,
                         mem=self.mem,
                         time=self.time,
                         gpu=self.gpu,
                         std_out=self.stdout_file,
                         std_err=self.stderr_file,
                         job_script=self.bash_script_file)
        if self.verbose:
            logging.info('CMD: {}'.format(cmd))
        try:
            res = sp.run(cmd, check=True, shell=True, stdout=sp.PIPE)
        except sp.CalledProcessError as e:
            raise e
        res = res.stdout.decode()
        try:
            m = re.search("Your job (\d+)", res)
            self.jobid = m.group(1)            
        except Exception as e:
            raise ValueError(e)
        
    def job_python_script(self):
        """
        """
        script = '''#!/usr/bin/env python
from __future__ import print_function
import os
import sys
import dill as pickle

if __name__ == '__main__':
    # load params
    with open(sys.argv[1], 'rb') as inF:
        params = pickle.load(inF)
    # load packages
    for pkg in params['pkgs']:
        exec('import {}'.format(pkg))
    # run function & serialize output
    with open(sys.argv[2], 'wb') as outF:
        try:
            pickle.dump(params['func'](params['args'], **params['kwargs']), outF)
        except TypeError:
            pickle.dump(params['func'](**params['kwargs']), outF)
        '''
        self.python_script_file = os.path.join(self.tmp_dir, 'script.py')
        with open(self.python_script_file, 'w') as outF:
            outF.write(script)
        if self.verbose:
            logging.info('File written: {}'.format(self.python_script_file))
        
    def job_bash_script(self):
        """        
        """
        script = '''#!/bin/bash
export OMP_NUM_THREADS=1
if [[ -f ~/.bashrc &&  $(grep -c "__conda_setup=" ~/.bashrc) -gt 0 && $(grep -c "unset __conda_setup" ~/.bashrc) -gt 0 ]]; then
   echo "Sourcing .bashrc" 1>&2
   . ~/.bashrc
else
   echo "Exporting conda PATH" 1>&2
   export PATH=/ebio/abt3_projects/software/dev/miniconda3_dev/bin:$PATH
fi

conda activate {conda_env}
python {exe} {params} {outfile}
        '''
        self.results_file = os.path.join(self.tmp_dir, 'results.pkl')
        script = script.format(conda_env = self.conda_env,
                               exe = self.python_script_file,
                               params = self.param_file,
                               outfile = self.results_file)
        self.bash_script_file = os.path.join(self.tmp_dir, 'script.sh')
        with open(self.bash_script_file, 'w') as outF:
            outF.write(script)
        if self.verbose:
            logging.info('File written: {}'.format(self.bash_script_file))
            
    def serialize(self, func, args=None, kwargs=dict(), pkgs=[]):
        """
        serializing all objects
        """
        d = {'func' : func, 'args' : args, 'kwargs' : kwargs, 'pkgs' : pkgs}
        outfile = os.path.join(self.tmp_dir, 'job_params.pkl')
        with open(outfile, 'wb') as outF:
            pickle.dump(d, outF)
        self.param_file = outfile
        if self.verbose:
            logging.info('File written: {}'.format(outfile))
         
    @property
    def time(self):
        return self._time
    @time.setter
    def time(self, x):
        if re.match('^[0-9]+$', str(x)):
            hours = int(int(x) / 60)
            minutes = int(x) % 60
            x = '{:0>2}:{:0>2}:00'.format(hours, minutes)
        self._time = x

    @property
    def mem(self):
        return self._mem
    @mem.setter
    def mem(self, x):
        x = str(int(x.rstrip('GMgm')))
        self._mem = x + 'G'
                          
    @property
    def tmp_dir(self):
        return self._tmp_dir
    @tmp_dir.setter
    def tmp_dir(self, x):
        if x is None:
            x = ''        
        y = str(uuid.uuid4()).replace('-', '')
        x = os.path.join(x, y)
        os.makedirs(x, exist_ok=True)
        self._tmp_dir = x   

          
# class Pool():
#     def __init__(self, threads, time, mem, gpu, tmp_dir):
#         pass
#         # self.threads = threads
#         # self.time = time
#         # self.mem = mem
#         # self.gpu = gpu
#         # self.tmp_dir = tmp_dir
#         # if threads > 1:
#         #     self.pool = mp.Pool(threads)
#         # else:
#         #     self.pool = None

#     def job(self, func, args, kwargs=dict()):
#         w = worker()
#         w.serialize(self.tmp_dir, func, args, kwargs)
            
#     @property
#     def time(self):
#         return self._time
#     @time.setter
#     def time(self, x):
#         if re.match('^[0-9]+$', str(x)):
#             hours = int(int(x) / 60)
#             minutes = int(x) % 60
#             x = '{:0>2}:{:0>2}:00'.format(hours, minutes)
#         self._time = x