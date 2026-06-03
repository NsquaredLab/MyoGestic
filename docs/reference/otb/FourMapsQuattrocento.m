% Routine for the real time plot of four maps.
% Details:
% - Direct communication with Quattrocento. This Matlab scripts doesn't need
% OT BioLab, direcly communicate with the TCP socket opened on the
% Quattrocento. It opens a TCP socket, set the configuration and reads back
% data at the desired sampling frequency.
% - Maps plotted from the signals coming from the four Multiple Inputs
% - Written for the ELSCH064NM2
%
% OT Bioelettronica
% March 20th 2017
% v 1.0


close all

TestDuration = 10;      % Total duration of the test in seconds
MapsARVEpoch = 0.25;    % Time epoch for the ARV estimation in seconds (must be multiple of RefreshRate)
RefreshRate = 0.125;    % Maps refresh rate in seconds
ColorScale = 1;         % Set the amplitude in mV corresponding to the white color (max range) in the color plots

%----------------------------------------
% 64 electrode matrix mapping by column (SD)
col{1} = [4,5,11,10,24,32,34,39,40,49,50,62,61];            % column no.1
col{2} = [3,6,12,9,23,31,33,38,48,41,51,63,60];             % column no.2
col{3} = [2,7,13,17,22,30,27,37,47,42,52,64,59];            % column no.3
col{4} = [1,8,14,18,21,29,26,36,46,43,53,56,58];            % column no.4
col{5} = [1,16,15,19,20,28,25,35,45,44,54,55,57];           % column no.5
n_column = 5;
n_row = 12;
%----------------------------------------

NumRefreshPerEpoch = MapsARVEpoch/RefreshRate;
NumCycles = TestDuration/RefreshRate;

% Sampling frequency values
Fsamp = [0 8 16 24];    % Codes to set the sampling frequency
FsampVal = [512 2048 5120 10240];
FSsel = 2;              
% FSsel  = 1 -> 512 Hz
% FSsel  = 2 -> 2048 Hz
% FSsel  = 3 -> 5120 Hz
% FSsel  = 4 -> 10240 Hz

% Channels numbers
NumChan = [0 2 4 6];    % Codes to set the number of channels
NumChanVal = [120 216 312 408];
NCHsel = 4;             
% NCHsel = 1 -> IN1, IN2, MULTIPLE IN1, AUX IN
% NCHsel = 2 -> IN1..IN4, MULTIPLE IN1, MULTIPLE IN2, AUX IN
% NCHsel = 3 -> IN1..IN6, MULTIPLE IN1..MULTIPLE IN3, AUX IN
% NCHsel = 4 -> IN1..IN8, MULTIPLE IN1..MULTIPLE IN4, AUX IN

AnOutSource = 0;        % Source input for analog output:
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
AnOutGain = bin2dec('00010000');
% bin2dec('00000000') = Gain on the Analog output equal to 1
% bin2dec('00010000') = Gain on the Analog output equal to 2
% bin2dec('00100000') = Gain on the Analog output equal to 4
% bin2dec('00110000') = Gain on the Analog output equal to 16

% Provide amplitude in mV
GainFactor = 5/2^16/150*1000;    
% 5 is the ADC input swing
% 2^16 is the resolution
% 150 is the gain
% 1000 to get the mV

% Generate the configuration string
ConfString(1) = bin2dec('10000000') + Fsamp(FSsel) + NumChan(NCHsel) + 1;
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

% Accessory channels
RampChan = NumChanVal(NCHsel)-7;
BuffChan = NumChanVal(NCHsel)-4;

% Number of samples for each read corresponding to the number of samples of the
% refresh rate
NumSampBlockRead = FsampVal(FSsel)*RefreshRate;
EpochSegment = 1;

DiffARVMatr1 = zeros(n_column,n_row,NumRefreshPerEpoch);
DiffARVMatr2 = zeros(n_column,n_row,NumRefreshPerEpoch);
DiffARVMatr3 = zeros(n_column,n_row,NumRefreshPerEpoch);
DiffARVMatr4 = zeros(n_column,n_row,NumRefreshPerEpoch);
DiffARVMatrOverEpoch1 = zeros(n_column,n_row);
DiffARVMatrOverEpoch2 = zeros(n_column,n_row);
DiffARVMatrOverEpoch3 = zeros(n_column,n_row);
DiffARVMatrOverEpoch4 = zeros(n_column,n_row);

% PC's active screen size
screen_size = get(0,'ScreenSize');
pc_width  = screen_size(3);
pc_height = screen_size(4);

% Matlab also does not consider the height of the figure's toolbar...
% Or the width of the border... they only care about the contents!
toolbar_height = 77;
window_border  = 5;

% The Format of Matlab is this:
% [left, bottom, width, height]
m_left   = pc_width/2 - pc_height/4;
m_bottom = 0;
m_height = pc_height-toolbar_height-1;
m_width  = pc_height/2;

h = figure;

% Set the correct position of the figure
set(h, 'Position', [m_left, m_bottom, m_width, m_height]);

gcf;

colormap hot;
subplot(2,2,1)
h1 = surf(DiffARVMatrOverEpoch1); view(270,90);
ylim ([1,5]);
xlim ([1,12]);
caxis([1 ColorScale/GainFactor])

subplot(2,2,2)
h2 = surf(DiffARVMatrOverEpoch2); view(270,90);
shading interp;
ylim ([1,5]);
xlim ([1,12]);
caxis([1 ColorScale/GainFactor])

subplot(2,2,3)
h3 = surf(DiffARVMatrOverEpoch3); view(270,90);
shading interp;
ylim ([1,5]);
xlim ([1,12]);
caxis([1 ColorScale/GainFactor])

subplot(2,2,4)
h4 = surf(DiffARVMatrOverEpoch4); view(270,90);
shading interp;
ylim ([1,5]);
xlim ([1,12]);
caxis([1 ColorScale/GainFactor])       

TCPPort = 23456;
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

while tcpSocket.BytesAvailable <= NumChanVal(NCHsel)*NumSampBlockRead
    pause(0.001);
end

for i = 1 : NumCycles
    
    while toc(tstart) <= RefreshRate
        pause(0.001);
    end
    
    tstart = tic;
    
    try
        % Read data
        emg = fread(tcpSocket, [NumChanVal(NCHsel), NumSampBlockRead], 'int16')';       
        
        if(i > 2/RefreshRate)
            EpochSegment = EpochSegment + 1;
            if(EpochSegment > NumRefreshPerEpoch)
                EpochSegment = 1;
            end

            % Differential signals and ARV
            for column = 1 : n_column
                for row = 1 : n_row
                    % Differential signals are estimated by subtracting signals on
                    % adjacent matrix electrodes

                    % Signals from Multiple IN1 (Channels 128..192)
                    SigDIF = emg(:,col{column}(row)+128) - emg(:,col{column}(row+1)+128);
                    ARV_diff = mean(abs(SigDIF)); %sqrt(sum(SigDIF.^2)/NumSampBlockRead);
                    DiffARVMatr1(column,row,EpochSegment) = ARV_diff;

                    % Signals from Multiple IN2 (Channels 193..256)
                    SigDIF = emg(:,col{column}(row)+192) - emg(:,col{column}(row+1)+192);
                    ARV_diff = mean(abs(SigDIF)); %sqrt(sum(SigDIF.^2)/NumSampBlockRead);
                    DiffARVMatr2(column,row,EpochSegment) = ARV_diff;

                    % Signals from Multiple IN3 (Channels 257..320)
                    SigDIF = emg(:,col{column}(row)+256) - emg(:,col{column}(row+1)+256);
                    ARV_diff = mean(abs(SigDIF)); %sqrt(sum(SigDIF.^2)/NumSampBlockRead);
                    DiffARVMatr3(column,row,EpochSegment) = ARV_diff;

                    % Signals from Multiple IN4 (Channels 321..384)
                    SigDIF = emg(:,col{column}(row)+320) - emg(:,col{column}(row+1)+320);
                    ARV_diff = mean(abs(SigDIF)); %sqrt(sum(SigDIF.^2)/NumSampBlockRead);
                    DiffARVMatr4(column,row,EpochSegment) = ARV_diff;
                end
            end

            DiffARVMatrOverEpoch1 = mean(DiffARVMatr1,3);                    
            DiffARVMatrOverEpoch2 = mean(DiffARVMatr2,3);
            DiffARVMatrOverEpoch3 = mean(DiffARVMatr3,3);
            DiffARVMatrOverEpoch4 = mean(DiffARVMatr4,3);

            gcf;
% 
            subplot(2,2,1)
            h1.ZData = DiffARVMatrOverEpoch1;
            shading interp;

            subplot(2,2,2)
            h2.ZData = DiffARVMatrOverEpoch2;
            shading interp;

            subplot(2,2,3)
            h3.ZData = DiffARVMatrOverEpoch3;
            shading interp;

            subplot(2,2,4)
            h4.ZData = DiffARVMatrOverEpoch4;
            shading interp;

%             plot(diff(emg(:,401)));
%             title([num2str(i) '/' num2str(NumCycles)]);
% 

        end
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
fwrite(tcpSocket, ConfString, 'uint8');

% Close the communication
clear 'tcpSocket'
