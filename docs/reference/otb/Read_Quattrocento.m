% Routine for the direct communication with Quattrocento
% This Matlab scripts doesn't need OT BioLab to communicate with Quattrocento.
% It opens a TCP socket, set the configuration of Quattrocento and reads back
% data at the desired sampling frequency.
%
% OT Bioelettronica
% June 15th 2023
% v 5.0

close all
clear all

NumCycles = 20;         % How many times MatLab reads data from Quattrocento
PlotChan = [1:16];      % Channels to plot
PlotTime = 1;           % Plot time in s
Decim = 64;             % 0 or 64

offset = 5000; %32768;
Fsamp = [0 8 16 24];    % Codes to set the sampling frequency

% Sampling frequency values
FsampVal = [512 2048 5120 10240];
FSsel = 2;              
% FSsel  = 1 -> 512 Hz
% FSsel  = 2 -> 2048 Hz
% FSsel  = 3 -> 5120 Hz
% FSsel  = 4 -> 10240 Hz
NumChan = [0 2 4 6];    % Codes to set the number of channels
% Channels numbers
NumChanVal = [120 216 312 408];
NCHsel = 4;             
% NCHsel = 1 -> IN1, IN2, MULTIPLE IN1, AUX IN
% NCHsel = 2 -> IN1..IN4, MULTIPLE IN1, MULTIPLE IN2, AUX IN
% NCHsel = 3 -> IN1..IN6, MULTIPLE IN1..MULTIPLE IN3, AUX IN
% NCHsel = 4 -> IN1..IN8, MULTIPLE IN1..MULTIPLE IN4, AUX IN
AnOutSource = 9;        % Source input for analog output:
% 0 = the analog output signal came from IN1
% 1 = the analog output signal came from IN2
% 2 = the analog output signal came from IN3
% 3 = the analog output signal came from IN4
% 4 = the analog output signal came from IN5
% 5 = the analog output signal came from IN6
% 6 = the analog output signal came from IN7
% 7 = the analog output signal came from IN8
% 8 = the analog output signal came from MULTIPLE IN1
% 9 = the analog output signal came from MULTIPLE IN2
% 10 = the analog output signal came from MULTIPLE IN3
% 11 = the analog output signal came from MULTIPLE IN4
% 12 = the analog output signal came from AUX IN
AnOutChan = 0;          % Channel for analog output
AnOutGain = bin2dec('00000000');
% bin2dec('00000000') = Gain on the Analog output equal to 1
% bin2dec('00010000') = Gain on the Analog output equal to 2
% bin2dec('00100000') = Gain on the Analog output equal to 4
% bin2dec('00110000') = Gain on the Analog output equal to 16

% Number of TCP socket port
TCPPort = 23456;

GainFactor = 5/2^16/150*1000;       %Provide amplitude in mV
% 5 is the ADC input swing
% 2^16 is the resolution
% 150 is the gain
% 1000 to get the mV

AuxGainFactor = 5/2^16/0.5;         % Gain factor to convert Aux Channels in V

% Create the command to send to Quattrocento
ConfString(1) = bin2dec('10000000') + Decim + Fsamp(FSsel) + NumChan(NCHsel) + 1;
ConfString(2) = AnOutGain + AnOutSource;
ConfString(3) = AnOutChan;
% -------- IN 1 -------- %
ConfString(4) = 0;
ConfString(5) = 0;
ConfString(6) = bin2dec('00010100');
% -------- IN 2 -------- %
ConfString(7) = 0;
ConfString(8) = 0;
ConfString(9) = bin2dec('00010100');
% -------- IN 3 -------- %
ConfString(10) = 0;
ConfString(11) = 0;
ConfString(12) = bin2dec('00010100');
% -------- IN 4 -------- %
ConfString(13) = 0;
ConfString(14) = 0;
ConfString(15) = bin2dec('00010100');
% -------- IN 5 -------- %
ConfString(16) = 0;
ConfString(17) = 0;
ConfString(18) = bin2dec('00010100');
% -------- IN 6 -------- %
ConfString(19) = 0;
ConfString(20) = 0;
ConfString(21) = bin2dec('00010100');
% -------- IN 7 -------- %
ConfString(22) = 0;
ConfString(23) = 0;
ConfString(24) = bin2dec('00010100');
% -------- IN 8 -------- %
ConfString(25) = 0;
ConfString(26) = 0;
ConfString(27) = bin2dec('00010100');
% -------- MULTIPLE IN 1 -------- %
ConfString(28) = 0;
ConfString(29) = 0;
ConfString(30) = bin2dec('00010100');
% -------- MULTIPLE IN 2 -------- %
ConfString(31) = 0;
ConfString(32) = 0;
ConfString(33) = bin2dec('00010100');
% -------- MULTIPLE IN 3 -------- %
ConfString(34) = 0;
ConfString(35) = 0;
ConfString(36) = bin2dec('00010100');
% -------- MULTIPLE IN 4 -------- %
ConfString(37) = 0;
ConfString(38) = 0;
ConfString(39) = bin2dec('00010100');
% ---------- CRC8 ---------- %
ConfString(40) = CRC8(ConfString, 39);

% Control channels
RampChan = NumChanVal(NCHsel)-7;
BuffChan = NumChanVal(NCHsel)-4;
TotSamp = 0;

% The function tcpip is substituted by the functions
% tcpserver/tcpclient from Matlab version 2022a

% Open the TCP socket
if verLessThan('matlab','9.12')
    tcpSocket = tcpip('169.254.1.10', TCPPort, 'NetworkRole', 'client');
    tcpSocket.InputBufferSize = 2*NumChanVal(NCHsel)*FsampVal(FSsel);
    fopen(tcpSocket);
    set(tcpSocket, 'ByteOrder', 'littleEndian');
else
   % Open the TCP socket as client
    tcpSocket = tcpclient('169.254.1.10',TCPPort);
    tcpSocket.InputBufferSize = 2*NumChanVal(NCHsel)*FsampVal(FSsel);
    fopen(tcpSocket);
    set(tcpSocket, 'ByteOrder', 'little-endian');
end

% Send the configuration to Quattrocento
fwrite(tcpSocket, ConfString, 'uint8');

tstart = tic;
a = 0;

ConfString(1) = ConfString(1) + bin2dec('00100000'); % Force the trigger to go hi (bit 5)
ConfString(40) = CRC8(ConfString, 39);  % Estimates the new CRC
pause(1)

fwrite(tcpSocket, ConfString, 'uint8');

% One second of data: 2 bytes * channels * Sampling frequency
% blockData = 2*NumChanVal(NCHsel)*FsampVal(FSsel);

for i = 1 : NumCycles
    
    while toc(tstart) <= PlotTime
        pause(0.001);
    end
    
    tstart = tic;
    
    try
        % Read data
            
        % Read one second of data into signed integer
        Data{i} = fread(tcpSocket, [NumChanVal(NCHsel), FsampVal(FSsel)], 'int16')';
  
        t = linspace(0, size(Data{i}, 1)/FsampVal(FSsel), size(Data{i}, 1));
        
        % Plot the signals
        % subplot(2,1,1)
        for ch = PlotChan
            plot(t, Data{i}(:,ch) + ch*offset)
            hold on
        end
        hold off
        title('Signals')
        xlim([0 PlotTime])
               
        % % Plot the buffer space
        % subplot(4,1,3)
        % plot(t, Data{i}(:,BuffChan))
        % xlim([0 PlotTime])
        % ylim([0 22000])
        % title('Buffer Space')
        % 
        % % Plot the sample counter
        % subplot(4,1,4)
        % plot(t, Data{i}(:,RampChan))
        % % Alternatively, plot the difference between subsequent samples
        % % It has to be always equal to 1 to check that no sample is lost:
        % %plot(t(1:end-1), diff(Data{i}(:,RampChan)))
        % xlim([0 PlotTime])
        % title('Sample Number')
        % 
        % xlabel('Time(s)')
               
    catch
        break;
    end
end

% Stop data transfer.
% !!! Important !!!
% During debug always stop data transfer before start a new
% session otherwise the sinchronization with Quattrocento is lost.

ConfString(1) = bin2dec('10000000');    % First byte that stop the data transer
ConfString(40) = CRC8(ConfString, 39);  % Estimates the new CRC

% Stop the data transfer
fwrite(tcpSocket, ConfString, 'uint8');

% Close the communication
clear tcpSocket



