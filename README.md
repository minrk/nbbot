# nbbot – IPython Notebook bot

This is a simple script for load-testing an IPython notebook server by taking the following steps:

1. open a notebook
2. create a kernel and connect websockets
2. execute all the cells of the notebook via the websockets (waiting for outputs)
3. save the original notebook (changes to the notebook output are not recorded)

Usage:

    python nbbot.py [--url=http://host:port[/base_url]] notebook.ipynb [notebook2.ipynb]
