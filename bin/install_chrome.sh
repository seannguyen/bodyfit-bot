#!/bin/bash

VERSION=`curl -s https://chromedriver.storage.googleapis.com/LATEST_RELEASE`
echo Using Chrome driver version $VERSION

case $(uname -s) in
  *Linux*) # Linux
    PLATFORM=linux64

    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
    sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
    apt-get update
    apt-get install -y google-chrome-stable
    echo Installed chrome version `google-chrome --version`
    ;;
  *Darwin*) # Mac
    PLATFORM=mac64
    ;;
  *) # Not support
    echo "This platform is not supported" 1>&2
    exit 64
esac

[[ ! -d temp ]] && mkdir temp
curl -s https://chromedriver.storage.googleapis.com/${VERSION}/chromedriver_${PLATFORM}.zip > temp/chromedriver.zip

[[ ! -d bin_lib ]] && mkdir bin_lib
unzip temp/chromedriver.zip -d bin_lib/

echo Finished Installing Chrome
