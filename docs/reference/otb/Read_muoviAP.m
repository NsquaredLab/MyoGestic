% Example script for communication with Muovi/Muovi+ through SyncStation
%
% This script builds the communication command starting from the values
% of few variables, open a socket for the connection with SyncStation and, 
% when the Sync is connected, sends the command and starts receiving data
%
% OT Bioelettronica
% v. 2.0

close all
clear all

TCPPort = 54320;   % Number of TCP socket port
NumCycles = 10;    % Number of recording cycles
OffsetEMG = 1;     % Offset between the channels' signals 
PlotTime = 1;

% ---------- Muovi 1 ------------------------------------------------------
Muovi1EN = 0;   % 1 = Muovi enabled, 0 = Muovi disabled
EMG1 = 1;       % 1 = EMG, 0 = EEG
Mode1 = 3;      % 0 = 32Ch Monop, 1 = 16Ch Monop, 2 = 32Ch ImpCk, 3 = 32Ch Test
% ---------- Muovi 2 ------------------------------------------------------
Muovi2EN = 0;   % 1 = Muovi enabled, 0 = Muovi disabled
EMG2 = 1;       % 1 = EMG, 0 = EEG
Mode2 = 3;      % 0 = 32Ch Monop, 1 = 16Ch Monop, 2 = 32Ch ImpCk, 3 = 32Ch Test
% ---------- Muovi 3 ------------------------------------------------------
Muovi3EN = 1;   % 1 = Muovi enabled, 0 = Muovi disabled
EMG3 = 1;       % 1 = EMG, 0 = EEG
Mode3 = 3;      % 0 = 32Ch Monop, 1 = 16Ch Monop, 2 = 32Ch ImpCk, 3 = 32Ch Test
% ---------- Muovi 4 ------------------------------------------------------
Muovi4EN = 0;   % 1 = Muovi enabled, 0 = Muovi disabled
EMG4 = 1;       % 1 = EMG, 0 = EEG
Mode4 = 3;      % 0 = 32Ch Monop, 1 = 16Ch Monop, 2 = 32Ch ImpCk, 3 = 32Ch Test
% ---------- Muovi+ 1/ Sessantaquattro+ 1 --------------------------------------------
SessnP5EN = 0;   % 1 = Muovi+/ Sessantaquattro+ enabled, 0 = Sessantaquattro+ disabled
EMG5 = 1;       % 1 = EMG, 0=EEG
Mode5 = 3;      % 0 = 64Ch Monop, 1 = 32Ch Monop, 2 = 64Ch ImpCk, 3 = 64Ch Test
% ---------- Muovi+ 2/ Sessantaquattro+ 2 --------------------------------------------
SessnP6EN = 0;   % 1 = Muovi+/ Sessantaquattro+ enabled, 0 = Muovi disabled
EMG6 = 1;       % 1 = EMG, 0 = EEG
Mode6 = 1;      % 0 = 64Ch Monop, 1 = 32Ch Monop, 2 = 64Ch ImpCk, 3 = 64Ch Test
                
% Number of acquired channel depending on the acquisition mode
NumChanVsModeMuovi = [38 22 38 38];
NumChanVsModeSessn = [68 36 68 68];

% Prevents error of the user in the variables' initialization
if Muovi1EN > 1 | Muovi2EN > 1 | Muovi3EN > 1 | Muovi4EN > 1 | SessnP5EN > 1 | SessnP6EN > 1
    disp("Error, set MuoviXEN values equal to 0 or 1")
    return;
end

if EMG1 > 1 | EMG2 > 1 | EMG3 > 1 | EMG4 > 1 | EMG5 > 1 | EMG6 > 1
    disp("Error, set EMGX values equal to 0 or 1")
    return;
end

if Mode1 > 3 | Mode2 > 3 | Mode3 > 3 | Mode4 > 3 | Mode5 > 3 | Mode6 > 3
    disp("Error, set ModeX values between to 0 and 7")
    return;
end

SizeComm = (Muovi1EN + Muovi2EN + Muovi3EN + Muovi4EN + SessnP5EN + SessnP6EN)*2;
ConfString(1) = SizeComm + 1;   %GO

% Create the command to send to Muovi/Muovi+/Sessantaquattro+
sampFreq = 500;
NumChan = 6;
j = 2;
if Muovi1EN == 1
    ConfString(j) = 0 + EMG1 * 8 + Mode1 * 2 + 1;
    NumChan = NumChan + NumChanVsModeMuovi(Mode1+1);
    if EMG1 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

if Muovi2EN == 1
    ConfString(j) = 16 + EMG2 * 8 + Mode2 * 2 + 1;
    NumChan = NumChan + NumChanVsModeMuovi(Mode2+1);
    if EMG2 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

if Muovi3EN == 1
    ConfString(j) = 32 + EMG3 * 8 + Mode3 * 2 + 1;
    NumChan = NumChan + NumChanVsModeMuovi(Mode3+1);
    if EMG3 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

if Muovi4EN == 1
    ConfString(j) = 48 + EMG4 * 8 + Mode4 * 2 + 1;
    NumChan = NumChan + NumChanVsModeMuovi(Mode4+1);
    if EMG4 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

if SessnP5EN == 1
    ConfString(j) = 64 + EMG5 * 8 + Mode5 * 2 + 1;
    NumChan = NumChan + NumChanVsModeSessn(Mode5+1);
    if EMG5 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

if SessnP6EN == 1
    ConfString(j) = 80 + EMG6 * 8 + Mode6 * 2 + 1;
    NumChan = NumChan + NumChanVsModeSessn(Mode6+1);
    if EMG6 == 1
        sampFreq = 2000;
    end
    j = j+1;
end

ConfString(j) = CRC8(ConfString, j-1);

% The function tcpip is substituted by the functions
% tcpserver/tcpclient from Matlab version 2022a

% Open the TCP socket
if verLessThan('matlab','9.12')
    tcpSocket = tcpip('192.168.76.1', TCPPort, 'NetworkRole', 'client');
    % Increase the input buffer size
    tcpSocket.InputBufferSize = NumChan * sampFreq * 2; % 2 s of data with all ch @ 2kHz
    % Wait into this function until a server is connected
    fopen(tcpSocket);
else
   % Open the TCP socket as client
    tcpSocket = tcpclient('192.168.76.1',TCPPort);

    % % Wait into this function until a server is connected
    % while(tcpSocket.Connected < 1)
    %    pause(0.1)
    % end
end


% One second of data: 2 bytes * channels * Sampling frequency
blockData = 2*NumChan*sampFreq*PlotTime;

% Send the configuration to Muovi station
fwrite(tcpSocket, ConfString, 'uint8');

for i = 1 : NumCycles
    i
    
    % Wait here until one second of data has been received
    while(tcpSocket.BytesAvailable < blockData)
    end

    if verLessThan('matlab','9.12')
        % Read one second of data into signed integer
        data = fread(tcpSocket, [NumChan, sampFreq*PlotTime], 'int16');
    else
        % Read one second of data into signed integer
        Temp = read(tcpSocket, NumChan*sampFreq, 'int16');
        data = reshape(Temp, NumChan, sampFreq);
    end
    
    if NumChan > 12
        subplot(3,1,1)
        hold off
        for j = 1 : NumChan - 12
            plot(data(j,:)) % + OffsetEMG*(j-1))
            hold on
        end

        subplot(3,1,2)
        hold off
        for j = NumChan - 11 : NumChan - 6
            plot(data(j,:)) % + OffsetEMG*(j-1))
            hold on
        end

        subplot(3,1,3)
        hold off
        for j = NumChan - 5 : NumChan
            plot(data(j,:))
            hold on
        end
    else
        hold off
        for j = 1 : NumChan
            plot(data(j,:))
            hold on
        end
    end
    
    drawnow
end

clear ConfString;
ConfString(1) = 0;
ConfString(2) = CRC8(ConfString, 1);

% Send the configuration to muovi station
fwrite(tcpSocket, ConfString, 'uint8');

clear tcpSocket


