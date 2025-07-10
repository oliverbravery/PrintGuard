FROM python:3-alpine

RUN pip install --pre printguard

EXPOSE 8000

CMD [ "printguard" ]