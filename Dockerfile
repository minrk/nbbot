FROM ipython/ipython

RUN pip install requests

ADD . /srv/nbbot/
WORKDIR /srv/nbbot/

ENTRYPOINT ["python", "nbbot.py"]
