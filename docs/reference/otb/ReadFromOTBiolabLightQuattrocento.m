%Script to READ signals from Quattrocento with OTBiolab Light. 
%As an example, only the ramp signal is plotted, which gives us information on the correct communication with the device

clear all
close all
fclose all
clc


nCh=384+16+8;           % Set the number of channels required
channelToPlot=384+16+1; % Set the channel to plot (ramp)
fSample=2048;           % Set sampling frequency
fRead=16;               % Set reading frequency
nCycles=30*fRead;       % Set number of read
timeSize = 2;

handles.hPlot =plot(nan,nan);


tRead=zeros(1,nCycles);
dataAvailable=zeros(1,nCycles);

if verLessThan('matlab','9.12')
    tcpSocket = tcpip('localhost',31000);
    set(tcpSocket, 'ByteOrder', 'littleEndian');
else
    tcpSocket = tcpclient('localhost',31000);
    set(tcpSocket, 'ByteOrder', 'little-Endian');
end

tcpSocket.InputBufferSize=nCh*fSample*10;
fopen(tcpSocket);
fwrite(tcpSocket,'startTX');
pause(0.01)
name=fread(tcpSocket,8);
disp((char(name')));
dataToPlot=zeros(1,fSample*2);
t=[1/fSample:1/fSample:timeSize] - timeSize;
handles.hPlot=plot(t,dataToPlot);

tic
for nCycle=1:nCycles
        data=fread(tcpSocket,[nCh,fSample/fRead],'int16');
        dataChannel=data(channelToPlot,:);
        t=t+(length(dataChannel)*1/fSample);
        dataToPlot=[dataToPlot(length(dataChannel)+1:end) dataChannel];
        %dataToPlot(1:10)
        set(handles.hPlot,'XData',t,'YData',dataToPlot);
        title([num2str(toc) ' s'])
        xlim([t(1) t(end)])
        ylim([-33000 33000]);
        drawnow
end

fwrite(tcpSocket,'stopTX');

fclose(tcpSocket);
